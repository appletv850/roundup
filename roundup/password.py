#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
#
"""Password handling (encoding, decoding).
"""
__docformat__ = 'restructuredtext'

import re
import string
import warnings

from base64 import b64encode, b64decode
from hashlib import md5, sha1

import roundup.anypy.random_ as random_

from roundup.anypy.strings import us2s, b2s, s2b


try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        import crypt
except ImportError:
    crypt = None

_bempty = b""
_bjoin = _bempty.join


def bchr(c):
    if bytes == str:
        # Python 2.
        return chr(c)
    else:
        # Python 3.
        return bytes((c,))


def bord(c):
    if bytes == str:
        # Python 2.
        return ord(c)
    else:
        # Python 3.  Elements of bytes are integers.
        return c


# NOTE: PBKDF2 hash is using this variant of base64 to minimize encoding size,
#      and have charset that's compatible w/ unix crypt variants
def h64encode(data):
    """encode using variant of base64"""
    return b2s(b64encode(data, b"./").strip(b"=\n"))


def h64decode(data):
    """decode using variant of base64"""
    data = s2b(data)
    off = len(data) % 4
    if off == 0:
        return b64decode(data, b"./")
    elif off == 1:
        raise ValueError("Invalid base64 input")
    elif off == 2:
        return b64decode(data + b"==", b"./")
    else:
        return b64decode(data + b"=", b"./")


try:
    from hashlib import pbkdf2_hmac

    def _pbkdf2(password, salt, rounds, keylen):
        return pbkdf2_hmac('sha1', password, salt, rounds, keylen)
except ImportError:
    # no hashlib.pbkdf2_hmac - make our own pbkdf2 function
    from struct import pack
    from hmac import HMAC

    def xor_bytes(left, right):
        "perform bitwise-xor of two byte-strings"
        return _bjoin(bchr(bord(l) ^ bord(r))
                      for l, r in zip(left, right))  # noqa: E741

    def _pbkdf2(password, salt, rounds, keylen):
        digest_size = 20  # sha1 generates 20-byte blocks
        total_blocks = int((keylen+digest_size-1)/digest_size)
        hmac_template = HMAC(password, None, sha1)
        out = _bempty
        for i in range(1, total_blocks+1):
            hmac = hmac_template.copy()
            hmac.update(salt + pack(">L", i))
            block = tmp = hmac.digest()
            for _j in range(rounds-1):
                hmac = hmac_template.copy()
                hmac.update(tmp)
                tmp = hmac.digest()
                # TODO: need to speed up this call
                block = xor_bytes(block, tmp)
            out += block
        return out[:keylen]


def ssha(password, salt):
    ''' Make ssha digest from password and salt.
    Based on code of Roberto Aguilar <roberto@baremetal.io>
    https://gist.github.com/rca/7217540
    '''
    shaval = sha1(password)  # nosec
    shaval.update(salt)
    ssha_digest = b2s(b64encode(shaval.digest() + salt).strip())
    return ssha_digest


def pbkdf2(password, salt, rounds, keylen):
    """pkcs#5 password-based key derivation v2.0

    :arg password: passphrase to use to generate key (if unicode,
     converted to utf-8)
    :arg salt: salt bytes to use when generating key
    :param rounds: number of rounds to use to generate key
    :arg keylen: number of bytes to generate

    If hashlib supports pbkdf2, uses it's implementation as backend.

    :returns:
        raw bytes of generated key
    """
    password = s2b(us2s(password))
    if keylen > 40:
        # NOTE: pbkdf2 allows up to (2**31-1)*20 bytes,
        # but m2crypto has issues on some platforms above 40,
        # and such sizes aren't needed for a password hash anyways...
        raise ValueError("key length too large")
    if rounds < 1:
        raise ValueError("rounds must be positive number")
    return _pbkdf2(password, salt, rounds, keylen)


class PasswordValueError(ValueError):
    """ The password value is not valid """
    pass


def pbkdf2_unpack(pbkdf2):
    """ unpack pbkdf2 encrypted password into parts,
        assume it has format "{rounds}${salt}${digest}
    """
    pbkdf2 = us2s(pbkdf2)
    try:
        rounds, salt, digest = pbkdf2.split("$")
    except ValueError:
        raise PasswordValueError("invalid PBKDF2 hash (wrong number of "
                                 "separators)")
    if rounds.startswith("0"):
        raise PasswordValueError("invalid PBKDF2 hash (zero-padded rounds)")
    try:
        rounds = int(rounds)
    except ValueError:
        raise PasswordValueError("invalid PBKDF2 hash (invalid rounds)")
    raw_salt = h64decode(salt)
    return rounds, salt, raw_salt, digest


def encodePassword(plaintext, scheme, other=None, config=None):
    """Encrypt the plaintext password.
    """
    if plaintext is None:
        plaintext = ""
    if scheme == "PBKDF2":
        if other:
            rounds, salt, raw_salt, digest = pbkdf2_unpack(other)
        else:
            raw_salt = random_.token_bytes(20)
            salt = h64encode(raw_salt)
            if config:
                rounds = config.PASSWORD_PBKDF2_DEFAULT_ROUNDS
            else:
                rounds = 10000
        if rounds < 1000:
            raise PasswordValueError("invalid PBKDF2 hash (rounds too low)")
        raw_digest = pbkdf2(plaintext, raw_salt, rounds, 20)
        return "%d$%s$%s" % (rounds, salt, h64encode(raw_digest))
    elif scheme == 'SSHA':
        if other:
            raw_other = b64decode(other)
            salt = raw_other[20:]
        else:
            # new password
            # variable salt length
            salt_len = random_.randbelow(52-36) + 36
            salt = random_.token_bytes(salt_len)
        s = ssha(s2b(plaintext), salt)
    elif scheme == 'SHA':
        s = sha1(s2b(plaintext)).hexdigest()  # nosec
    elif scheme == 'MD5':
        s = md5(s2b(plaintext)).hexdigest()  # nosec
    elif scheme == 'crypt':
        if crypt is None:
            raise PasswordValueError(
                'Unsupported encryption scheme %r' % scheme)
        if other is not None:
            salt = other
        else:
            saltchars = './0123456789'+string.ascii_letters
            salt = random_.choice(saltchars) + random_.choice(saltchars)
        s = crypt.crypt(plaintext, salt)
    elif scheme == 'plaintext':
        s = plaintext
    else:
        raise PasswordValueError('Unknown encryption scheme %r' % scheme)
    return s


def generatePassword(length=12):
    chars = string.ascii_letters+string.digits
    password = [random_.choice(chars) for x in range(length - 1)]
    # make sure there is at least one digit
    digitidx = random_.randbelow(length)
    password[digitidx:digitidx] = [random_.choice(string.digits)]
    return ''.join(password)


class JournalPassword:
    """ Password dummy instance intended for journal operation.
        We do not store passwords in the journal any longer.  The dummy
        version only reads the encryption scheme from the given
        encrypted password.
    """
    default_scheme = 'PBKDF2'        # new encryptions use this scheme
    pwre = re.compile(r'{(\w+)}(.+)')

    def __init__(self, encrypted=''):
        if isinstance(encrypted, self.__class__):
            self.scheme = encrypted.scheme or self.default_scheme
        else:
            m = self.pwre.match(encrypted)
            if m:
                self.scheme = m.group(1)
            else:
                self.scheme = self.default_scheme
        self.password = ''

    def dummystr(self):
        """ return dummy string to store in journal
            - reports scheme, but nothing else
        """
        return "{%s}*encrypted*" % (self.scheme,)

    __str__ = dummystr

    def __eq__(self, other):
        """Compare this password against another password."""
        # check to see if we're comparing instances
        if isinstance(other, self.__class__):
            if self.scheme != other.scheme:
                return False
            return self.password == other.password

        # assume password is plaintext
        if self.password is None:
            raise ValueError('Password not set')
        return self.password == encodePassword(other, self.scheme,
                                               self.password or None)

    def __ne__(self, other):
        return not self.__eq__(other)


class Password(JournalPassword):
    """The class encapsulates a Password property type value in the database.

    The encoding of the password is one if None, 'SHA', 'MD5' or 'plaintext'.
    The encodePassword function is used to actually encode the password from
    plaintext. The None encoding is used in legacy databases where no
    encoding scheme is identified.

    The scheme is stored with the encoded data in the database:
        {scheme}data

    Example usage:
    >>> p = Password('sekrit')
    >>> p == 'sekrit'
    1
    >>> p != 'not sekrit'
    1
    >>> 'sekrit' == p
    1
    >>> 'not sekrit' != p
    1
    """
    # TODO: code to migrate from old password schemes.

    deprecated_schemes = ["SHA", "MD5", "crypt", "plaintext"]
    known_schemes = ["PBKDF2", "SSHA"] + deprecated_schemes

    def __init__(self, plaintext=None, scheme=None, encrypted=None,
                 strict=False, config=None):
        """Call setPassword if plaintext is not None."""
        if scheme is None:
            scheme = self.default_scheme
        if plaintext is not None:
            self.setPassword(plaintext, scheme, config=config)
        elif encrypted is not None:
            self.unpack(encrypted, scheme, strict=strict, config=config)
        else:
            self.scheme = self.default_scheme
            self.password = None
            self.plaintext = None

    def __repr__(self):
        return self.__str__()

    def needs_migration(self):
        """ Password has insecure scheme or other insecure parameters
            and needs migration to new password scheme
        """
        if self.scheme in self.deprecated_schemes:
            return True
        rounds, salt, raw_salt, digest = pbkdf2_unpack(self.password)
        if rounds < 1000:
            return True
        return False

    def unpack(self, encrypted, scheme=None, strict=False, config=None):
        """Set the password info from the scheme:<encryted info> string
           (the inverse of __str__)
        """
        m = self.pwre.match(encrypted)
        if m:
            self.scheme = m.group(1)
            self.password = m.group(2)
            self.plaintext = None
        else:
            # currently plaintext - encrypt
            self.setPassword(encrypted, scheme, config=config)
        if strict and self.scheme not in self.known_schemes:
            raise PasswordValueError("Unknown encryption scheme: %r" %
                                     (self.scheme,))

    def setPassword(self, plaintext, scheme=None, config=None):
        """Sets encrypts plaintext."""
        if scheme is None:
            scheme = self.default_scheme
        self.scheme = scheme
        self.password = encodePassword(plaintext, scheme, config=config)
        self.plaintext = plaintext

    def __str__(self):
        """Stringify the encrypted password for database storage."""
        if self.password is None:
            raise ValueError('Password not set')
        return '{%s}%s' % (self.scheme, self.password)


def test_missing_crypt():
    p = encodePassword('sekrit', 'crypt')      # noqa: F841   - test only


def test():
    # SHA
    p = Password('sekrit')
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # MD5
    p = Password('sekrit', 'MD5')
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # crypt
    if crypt:  # not available on Windows
        p = Password('sekrit', 'crypt')
        assert Password(encrypted=str(p)) == 'sekrit'
        assert 'sekrit' == Password(encrypted=str(p))
        assert p == 'sekrit'
        assert p != 'not sekrit'
        assert 'sekrit' == p
        assert 'not sekrit' != p

    # SSHA
    p = Password('sekrit', 'SSHA')
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # PBKDF2 - low level function
    from binascii import unhexlify
    k = pbkdf2("password", b"ATHENA.MIT.EDUraeburn", 1200, 32)
    assert k == unhexlify("5c08eb61fdf71e4e4ec3cf6ba1f5512ba7e52ddbc5e5142f708a31e2e62b1e13")

    # PBKDF2 - hash function
    h = "5000$7BvbBq.EZzz/O0HuwX3iP.nAG3s$g3oPnFFaga2BJaX5PoPRljl4XIE"
    assert encodePassword("sekrit", "PBKDF2", h) == h

    # PBKDF2 - high level integration
    p = Password('sekrit', 'PBKDF2')
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p


if __name__ == '__main__':
    test()
    test_missing_crypt()

# vim: set filetype=python sts=4 sw=4 et si :
