from web3 import Web3
import time
import os
import web3

# Konfigurasi
MAIN_WALLET = "0xYourMainWalletAddress"  # Ganti dengan alamat wallet utama kamu
RPC_URL = "https://rpc.0g.ai"  # RPC URL untuk jaringan 0g.ai
CHAIN_ID = 123  # Ganti dengan chain ID jaringan 0g.ai (periksa di dokumentasi resmi)
WALLET_FILE = "wallet.txt"

# Inisialisasi Web3
try:
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise Exception("Gagal terhubung ke RPC URL")
    print("Berhasil terhubung ke RPC")
    print(f"Chain ID dari jaringan: {w3.eth.chain_id}")
except Exception as e:
    print(f"Error inisialisasi Web3: {e}")
    exit(1)

# Fungsi untuk transfer saldo ke wallet utama
def transfer_to_main_wallet(wallet_address, private_key):
    try:
        # Inisialisasi akun pengirim
        account = w3.eth.account.from_key(private_key)
        print(f"[{wallet_address}] Akun pengirim berhasil diinisialisasi")

        # Cek saldo wallet
        balance = w3.eth.get_balance(wallet_address)
        gas_price = w3.eth.gas_price
        gas_limit = 21000  # Gas limit untuk transfer sederhana
        
        print(f"[{wallet_address}] Saldo: {w3.from_wei(balance, 'ether')} ETH")
        print(f"[{wallet_address}] Gas Price: {w3.from_wei(gas_price, 'gwei')} Gwei")
        print(f"[{wallet_address}] Gas Limit: {gas_limit}")

        # Hitung saldo yang bisa dikirim (kurangi gas fee)
        gas_fee = gas_price * gas_limit
        amount_to_send = balance - gas_fee
        
        if amount_to_send <= 0:
            print(f"Saldo tidak cukup untuk transfer dari {wallet_address} (Saldo: {w3.from_wei(balance, 'ether')} ETH, Gas Fee: {w3.from_wei(gas_fee, 'ether')} ETH)")
            return False

        # Buat transaksi
        tx = {
            "to": MAIN_WALLET,
            "value": amount_to_send,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "nonce": w3.eth.get_transaction_count(wallet_address),
            "chainId": CHAIN_ID
        }
        print(f"[{wallet_address}] Transaksi yang akan ditandatangani: {tx}")

        # Tanda tangani transaksi
        signed_tx = account.sign_transaction(tx)
        print(f"[{wallet_address}] Transaksi berhasil ditandatangani: {signed_tx}")

        # Kirim transaksi (gunakan raw_transaction untuk versi web3.py 6.x dan 7.x)
        raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
        if raw_tx is None:
            raise AttributeError("Tidak dapat menemukan raw_transaction atau rawTransaction pada objek SignedTransaction")
        
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        print(f"Transfer dari {wallet_address} ke {MAIN_WALLET} berhasil! Tx Hash: {tx_hash.hex()}")
        
        # Simpan hash transaksi transfer
        with open("transfer_hashes.txt", "a") as f:
            f.write(f"{wallet_address} -> {MAIN_WALLET}: {tx_hash.hex()}\n")
        return True
    except Exception as e:
        print(f"Error saat transfer dari {wallet_address}: {e}")
        return False

# Fungsi untuk membaca wallet dari wallet.txt dan transfer saldo
def transfer_all_to_main():
    if not os.path.exists(WALLET_FILE):
        print(f"File {WALLET_FILE} tidak ditemukan. Tidak ada wallet untuk ditransfer.")
        return

    with open(WALLET_FILE, "r") as f:
        wallets = [line.strip() for line in f.readlines() if line.strip()]
    
    if not wallets:
        print(f"File {WALLET_FILE} kosong. Tidak ada wallet untuk ditransfer.")
        return

    for wallet_line in wallets:
        try:
            # Format: address - private_key
            wallet_address, private_key = wallet_line.split(" - ")
            print(f"Memproses transfer dari {wallet_address}...")
            transfer_to_main_wallet(wallet_address, private_key)
            time.sleep(5)  # Jeda antar transaksi untuk hindari rate limit
        except Exception as e:
            print(f"Error memproses wallet {wallet_line}: {e}")

# Fungsi utama
def main():
    print("Mulai transfer saldo ke wallet utama...")
    print(f"Versi web3.py yang digunakan: {web3.__version__}")
    transfer_all_to_main()
    print("Transfer selesai.")

if __name__ == "__main__":
    main()
