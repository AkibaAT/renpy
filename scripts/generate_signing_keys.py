#!/usr/bin/env python3
"""
Generate Ed25519 key pair for signing Oka'Py updates and extensions.

Ed25519 provides:
- 128-bit security level (equivalent to RSA-3072)
- Very fast signing and verification
- Small keys (32 bytes) and signatures (64 bytes)
- No known weaknesses

Usage:
    python scripts/generate_signing_keys.py <private_key_file> <public_key_file>

Example:
    python scripts/generate_signing_keys.py keys/okapy_private.pem launcher/game/okapy_public.pem
"""

import argparse
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def main():
    ap = argparse.ArgumentParser(description="Generate Ed25519 key pair for signing")
    ap.add_argument("private", help="Path to save the private key (PEM format)")
    ap.add_argument("public", help="Path to save the public key (PEM format)")
    args = ap.parse_args()

    # Generate Ed25519 key pair
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save private key (unencrypted PEM)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open(args.private, "wb") as f:
        f.write(private_pem)

    # Save public key (PEM)
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    with open(args.public, "wb") as f:
        f.write(public_pem)

    print(f"Generated Ed25519 key pair:")
    print(f"  Private key: {args.private}")
    print(f"  Public key:  {args.public}")
    print()
    print("IMPORTANT:")
    print("  - Keep the private key SECRET")
    print("  - Add private key path to .gitignore")
    print("  - Store private key in GitHub Secrets for CI/CD")
    print("  - The public key should be committed to the repository")


if __name__ == "__main__":
    main()
