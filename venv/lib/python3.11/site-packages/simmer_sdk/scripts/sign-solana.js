#!/usr/bin/env node
/**
 * Solana Transaction Signing Helper
 *
 * Signs a Solana transaction locally using the user's private key.
 * Called by the Python SDK via subprocess.
 *
 * Usage:
 *   node sign-solana.js <base64_unsigned_tx>
 *
 * Environment:
 *   SOLANA_PRIVATE_KEY - Base58-encoded Solana private key
 *
 * Output:
 *   Base64-encoded signed transaction (to stdout)
 *   Errors go to stderr with non-zero exit code
 *
 * SECURITY NOTE: The private key is read from environment and never logged.
 */

const { Keypair, VersionedTransaction } = require('@solana/web3.js');
const bs58 = require('bs58');

function main() {
  // Get the unsigned transaction from command line
  const unsignedTxBase64 = process.argv[2];
  if (!unsignedTxBase64) {
    console.error('Usage: node sign-solana.js <base64_unsigned_tx>');
    process.exit(1);
  }

  // Get the private key from environment
  const solanaKey = process.env.SOLANA_PRIVATE_KEY;
  if (!solanaKey) {
    console.error('Error: SOLANA_PRIVATE_KEY environment variable not set');
    process.exit(1);
  }

  try {
    // Decode the private key (base58 encoded)
    let secretKeyBytes;
    try {
      secretKeyBytes = bs58.decode(solanaKey);
    } catch (e) {
      console.error('Error: Invalid SOLANA_PRIVATE_KEY format. Expected base58-encoded secret key.');
      process.exit(1);
    }

    // Validate key length (Solana secret keys are 64 bytes)
    if (secretKeyBytes.length !== 64) {
      console.error(`Error: Invalid key length. Expected 64 bytes, got ${secretKeyBytes.length}`);
      process.exit(1);
    }

    // Create keypair from secret key
    const wallet = Keypair.fromSecretKey(secretKeyBytes);

    // Decode the unsigned transaction
    const txBytes = Buffer.from(unsignedTxBase64, 'base64');
    const tx = VersionedTransaction.deserialize(txBytes);

    // Sign the transaction
    tx.sign([wallet]);

    // Output the signed transaction as base64
    const signedTxBase64 = Buffer.from(tx.serialize()).toString('base64');
    console.log(signedTxBase64);

  } catch (error) {
    console.error(`Error signing transaction: ${error.message}`);
    process.exit(1);
  }
}

main();
