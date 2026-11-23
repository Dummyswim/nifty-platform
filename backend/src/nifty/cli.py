import argparse
import getpass
import json
import sys

from nifty.security import hash_password


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nifty")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hash-password", help="prompt and print APP_PASSWORD_HASH=...")
    sub.add_parser("openapi", help="print the OpenAPI JSON")
    args = ap.parse_args(argv)
    if args.cmd == "hash-password":
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat: ") or not pw:
            print("passwords differ or empty", file=sys.stderr)
            return 1
        # single-quoted: '$' would otherwise be interpolated by compose/dotenv
        print(f"APP_PASSWORD_HASH='{hash_password(pw)}'")
    elif args.cmd == "openapi":
        from nifty.api.main import create_app

        print(json.dumps(create_app().openapi()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
