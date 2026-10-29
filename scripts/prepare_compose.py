"""Generate private Compose configuration without printing secrets or replacing files."""
import argparse
import ipaddress
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def environment_values(max_bytes, version_max_files, version_max_bytes, bind_address, http_port):
    """Fresh random private values plus the explicit storage limits, in compose.env order."""
    return {
        'AR_DATABASE_PASSWORD': secrets.token_urlsafe(32),
        'AR_TOKEN_SECRET': secrets.token_urlsafe(64),
        'AR_BOOTSTRAP_PASSWORD': secrets.token_urlsafe(24),
        'AR_STORAGE_MAX_BYTES': str(max_bytes),
        'AR_STORAGE_VERSION_MAX_FILES': str(version_max_files),
        'AR_STORAGE_VERSION_MAX_BYTES': str(version_max_bytes),
        'AR_BIND_ADDRESS': bind_address,
        'AR_HTTP_PORT': str(http_port),
    }


def create_environment_file(destination, values):
    """Exclusive 0600 creation; raises FileExistsError instead of replacing existing credentials."""
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(key + '=' + value for key, value in values.items()) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-bytes', type=int, required=True, help='Largest single uploaded file, in bytes')
    parser.add_argument('--version-max-files', type=int, default=1000, help='Largest file count per content version')
    parser.add_argument('--version-max-bytes', type=int, default=4294967296, help='Largest total bytes per content version')
    parser.add_argument('--test', action='store_true', help='Use isolated test config and port 18082')
    parser.add_argument('--bind-address', default='127.0.0.1',
                        help='IPv4/IPv6 host address for the gateway; ignored with --test')
    parser.add_argument('--http-port', type=int, default=18081,
                        help='Host port for the gateway; ignored with --test')
    args = parser.parse_args()
    for option in ('max_bytes', 'version_max_files', 'version_max_bytes'):
        if getattr(args, option) <= 0:
            parser.error('--' + option.replace('_', '-') + ' must be positive')
    try:
        ipaddress.ip_address(args.bind_address)
    except ValueError:
        parser.error('--bind-address must be an IPv4 or IPv6 address')
    if not 1 <= args.http_port <= 65535:
        parser.error('--http-port must be between 1 and 65535')
    bind_address = '127.0.0.1' if args.test else args.bind_address
    http_port = 18082 if args.test else args.http_port
    destination = ROOT / ('config/compose-test.env' if args.test else 'config/compose.env')
    values = environment_values(args.max_bytes, args.version_max_files, args.version_max_bytes, bind_address, http_port)
    try:
        create_environment_file(destination, values)
    except FileExistsError:
        parser.error('Configuration already exists; refusing to replace credentials')
    print('Created private configuration:', destination.relative_to(ROOT))
    print('No credentials printed. Open the private file locally for initial bootstrap login.')


if __name__ == '__main__':
    main()
