#!/usr/bin/env python3
"""
Signs update.json and extension manifest files using Ed25519.

Usage:
    python scripts/sign_update.py <private_key> <file_to_sign>

The signature is written to <file_to_sign>.sig as base64-encoded bytes.
"""

import argparse
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    ap = argparse.ArgumentParser(description="Sign a file with Ed25519")
    ap.add_argument("private", help="Path to the private key (PEM format)")
    ap.add_argument("file", help="Path to the file to sign")
    args = ap.parse_args()

    # Load private key
    with open(args.private, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Expected Ed25519 private key")

    # Read file to sign
    with open(args.file, "rb") as f:
        message = f.read()

    # Sign
    signature = private_key.sign(message)

    # Write base64-encoded signature
    with open(args.file + ".sig", "wb") as f:
        f.write(base64.b64encode(signature))

    print(f"Signed: {args.file}")
    print(f"Signature: {args.file}.sig")


if __name__ == "__main__":
    main()
