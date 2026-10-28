"""Reject private runtime files in a Git revision; never print file contents."""
import argparse
import fnmatch
from pathlib import PurePosixPath
import subprocess


def blocked_path(name):
    path = PurePosixPath(name)
    parts = path.parts
    base = path.name.lower()
    if base == '.env.example':
        return False
    if any(p in {'logs', '.ssh', '.aws', '.venv', '__pycache__'} for p in parts):
        return True
    if name.startswith(('runtime/cache/', 'runtime/venv/', 'archive/backups/')):
        return True
    if base in {'echo_devices.json', 'speaker_profiles.json', 'secrets.yaml', 'secrets.yml'}:
        return True
    return any(fnmatch.fnmatch(base, pattern) for pattern in (
        '.env', '.env.*', '.ssh_askpass*', '*credentials*.json',
        '*.pem', '*.key', '*.p12', '*.pfx', '*.wav', '*.mp3', '*.flac', '*.ogg',
        '*.ses', '*.bak*', 'id_rsa*', 'id_ed25519*',
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    args = parser.parse_args()
    revision = subprocess.check_output(['git','rev-parse','--verify',args.ref+'^{commit}'],text=True).strip()
    names = subprocess.check_output(['git','ls-tree','-rz','--name-only',revision]).decode().split('\0')
    blocked = [name for name in names if name and blocked_path(name)]
    if blocked:
        print('Private/generated paths must not be published:')
        for name in blocked:
            print(name)
        return 1
    print('Public-file guard passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
