import requests
import time
import random
from web3 import Web3
import os
import re
import json
from datetime import datetime, timedelta
import subprocess
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor

# Konfigurasi
HCAPTCHA_SITEKEY = "1230eb62-f50c-4da4-a736-da5c3c342e8e"
HCAPTCHA_PAGE_URL = "https://hub.0g.ai/faucet"
FAUCET_API_URL = "https://992dkn4ph6.execute-api.us-west-1.amazonaws.com/"
CAPTCHA_API_KEY = "2captchaAPI"  # Ganti dengan API Key 2Captcha
FAUCET_TOKEN = "A0GI"  # Token statis, ganti jika dinamis
PROXY_LIST_FILE = "proxy.txt"
USED_PROXIES = set()
CLAIM_HISTORY_FILE = "claim_history.txt"
WALLET_FILE = "wallet.txt"
TX_HASHES_FILE = "tx_hashes.txt"  # File untuk menyimpan hash transaksi berhasil
CAPTCHA_TIMEOUT = 60  # Timeout maksimum untuk pemecahan captcha (detik)
MAX_PARALLEL_CAPTCHAS = 3  # Jumlah captcha yang diproses secara paralel
REQUEST_TIMEOUT = 40  # Timeout untuk request ke faucet (detik)
RPC_URL = "https://rpc.0g.ai"  # Ganti dengan RPC URL jaringan 0g.ai

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://hub.0g.ai",
    "referer": "https://hub.0g.ai/",
    "sec-ch-ua": '"Chromium";v="111", "Not(A:Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
}

# Inisialisasi Web3
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("Gagal terhubung ke RPC URL. Pastikan RPC_URL benar.")
    exit(1)

# Fungsi untuk mendapatkan proxy yang tersedia (rotasi proxy)
def get_available_proxy():
    if not os.path.exists(PROXY_LIST_FILE):
        print(f"File {PROXY_LIST_FILE} tidak ditemukan. Melanjutkan tanpa proxy.")
        return None

    with open(PROXY_LIST_FILE, "r") as f:
        proxies = [p.strip() for p in f.readlines() if p.strip()]
    
    if not proxies:
        print(f"File {PROXY_LIST_FILE} kosong. Melanjutkan tanpa proxy.")
        return None

    available_proxies = [p for p in proxies if p not in USED_PROXIES]
    
    if not available_proxies:
        print("Semua proxy sudah digunakan. Mengosongkan daftar USED_PROXIES untuk rotasi ulang.")
        USED_PROXIES.clear()
        available_proxies = proxies
    
    proxy = random.choice(available_proxies)
    USED_PROXIES.add(proxy)
    return proxy

# Fungsi untuk menyelesaikan hCaptcha secara manual dengan timeout
def solve_captcha(wallet_address):
    try:
        start_time = time.time()
        url = f"http://2captcha.com/in.php?key={CAPTCHA_API_KEY}&method=hcaptcha&sitekey={HCAPTCHA_SITEKEY}&pageurl={HCAPTCHA_PAGE_URL}&json=1"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        result = response.json()
        print(f"[{wallet_address}] Pengiriman captcha ke 2Captcha selesai dalam {time.time() - start_time:.2f} detik")
        
        if result["status"] != 1:
            raise Exception(f"Failed to send captcha to 2Captcha: {result.get('request')}")
        
        request_id = result["request"]
        print(f"[{wallet_address}] Captcha sent to 2Captcha, Request ID: {request_id}")

        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > CAPTCHA_TIMEOUT:
                raise Exception(f"Pemecahan captcha terlalu lama, melebihi {CAPTCHA_TIMEOUT} detik")

            time.sleep(5)
            poll_start = time.time()
            url = f"http://2captcha.com/res.php?key={CAPTCHA_API_KEY}&action=get&id={request_id}&json=1"
            result = requests.get(url, timeout=REQUEST_TIMEOUT).json()
            print(f"[{wallet_address}] Polling selesai dalam {time.time() - poll_start:.2f} detik")
            
            if result["status"] == 1:
                captcha_response = result["request"]
                print(f"[{wallet_address}] Captcha solved successfully dalam {time.time() - start_time:.2f} detik")
                return captcha_response
            print(f"[{wallet_address}] Waiting for captcha solution... ({elapsed_time:.2f} detik berlalu)")
    except Exception as e:
        print(f"[{wallet_address}] Error solving captcha: {e}")
        return None

# Fungsi untuk memeriksa apakah wallet sudah pernah berhasil diklaim
def has_successful_claim(wallet_address):
    if not os.path.exists(TX_HASHES_FILE):
        return False
    
    with open(TX_HASHES_FILE, "r") as f:
        for line in f:
            if wallet_address in line:
                return True
    return False

# Fungsi untuk memeriksa saldo wallet di blockchain
def check_balance(wallet_address, previous_balance=None):
    try:
        balance = w3.eth.get_balance(wallet_address)
        print(f"[{wallet_address}] Saldo saat ini: {w3.from_wei(balance, 'ether')} ETH")
        if previous_balance is not None and balance > previous_balance:
            print(f"[{wallet_address}] Saldo bertambah dari {w3.from_wei(previous_balance, 'ether')} ETH. Klaim kemungkinan berhasil.")
            return True, balance
        return False, balance
    except Exception as e:
        print(f"[{wallet_address}] Error memeriksa saldo: {e}")
        return False, None

# Fungsi untuk klaim faucet
def claim_faucet(wallet_address, hcaptcha_token, use_proxy=True):
    proxy = get_available_proxy() if use_proxy else None
    retries = 3
    previous_balance = w3.eth.get_balance(wallet_address) if use_proxy else None

    while retries > 0:
        try:
            print(f"[{wallet_address}] Using proxy: {proxy or 'None'}")
            proxies = {"http": proxy, "https": proxy} if proxy else None
            
            payload = {
                "address": wallet_address,
                "hcaptchaToken": hcaptcha_token,
                "token": FAUCET_TOKEN
            }
            response = requests.post(
                FAUCET_API_URL,
                json=payload,
                headers=HEADERS,
                proxies=proxies,
                timeout=REQUEST_TIMEOUT
            )
            response_data = response.json()
            print(f"[{wallet_address}] Faucet Response: {response_data}")
            
            # Perbaiki regex untuk hash transaksi (64 karakter hex setelah 0x)
            if "message" in response_data and re.match(r"^0x[a-fA-F0-9]{64}$", response_data["message"]):
                print(f"[{wallet_address}] Claim successful! Transaction hash: {response_data['message']}")
                with open(TX_HASHES_FILE, "a") as f:
                    f.write(f"{wallet_address}: {response_data['message']}\n")
                return response_data
            return response_data
        except requests.exceptions.RequestException as e:
            error_msg = e.response.json() if hasattr(e, "response") and e.response else str(e)
            print(f"[{wallet_address}] Error with proxy {proxy}: {error_msg}")
            
            # Cek saldo di blockchain untuk memastikan apakah klaim sudah berhasil
            has_increased, new_balance = check_balance(wallet_address, previous_balance)
            if has_increased or has_successful_claim(wallet_address):
                print(f"[{wallet_address}] Klaim kemungkinan sudah berhasil (saldo bertambah atau sudah ada di tx_hashes). Skipping retry...")
                with open(TX_HASHES_FILE, "a") as f:
                    f.write(f"{wallet_address}: unknown_tx_hash (detected via balance)\n")
                return {"message": "Claim detected via balance"}
            
            if proxy:
                USED_PROXIES.add(proxy)
            proxy = get_available_proxy()
            retries -= 1
            time.sleep(5)
    return None

# Fungsi untuk membaca claim history
def load_claim_history():
    if not os.path.exists(CLAIM_HISTORY_FILE):
        return {}
    
    with open(CLAIM_HISTORY_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

# Fungsi untuk menyimpan claim history
def save_claim_history(history):
    with open(CLAIM_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

# Fungsi untuk membaca wallet dari wallet.txt
def load_wallets():
    if not os.path.exists(WALLET_FILE):
        print(f"File {WALLET_FILE} tidak ditemukan. Silakan jalankan script untuk generate wallet terlebih dahulu.")
        return []
    
    with open(WALLET_FILE, "r") as f:
        wallets = [line.strip() for line in f.readlines() if line.strip()]
    return wallets

# Fungsi untuk menampilkan progress
def display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets):
    processed = progress_counter[0]
    success = success_counter[0]
    failed = failed_counter[0]
    cooldown = cooldown_counter[0]
    percentage = (processed / total_wallets) * 100
    print(f"\nProgress: {processed}/{total_wallets} wallet selesai ({percentage:.2f}%)")
    print(f"Berhasil: {success} | Gagal: {failed} | Cooldown: {cooldown}\n")

# Fungsi untuk memproses satu wallet (dipanggil dalam thread)
def process_wallet(wallet_line, claim_history, current_time, result_queue, progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets, lock):
    try:
        wallet_address, private_key = wallet_line.split(" - ")
        print(f"Memproses klaim untuk {wallet_address}...")

        # Cek apakah wallet sudah pernah berhasil diklaim
        if has_successful_claim(wallet_address):
            last_claim_str = claim_history.get(wallet_address)
            if last_claim_str:
                last_claim = datetime.fromisoformat(last_claim_str)
                time_since_last_claim = (current_time - last_claim).total_seconds()
                if time_since_last_claim < 24 * 60 * 60:  # 24 jam dalam detik
                    print(f"Wallet {wallet_address} sudah berhasil diklaim sebelumnya dan masih dalam cooldown. Sisa waktu: {int((24 * 60 * 60 - time_since_last_claim) / 3600)} jam.")
                    with lock:
                        progress_counter[0] += 1
                        cooldown_counter[0] += 1
                        display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
                    return

        # Cek waktu klaim terakhir
        last_claim_str = claim_history.get(wallet_address)
        if last_claim_str:
            last_claim = datetime.fromisoformat(last_claim_str)
            time_since_last_claim = (current_time - last_claim).total_seconds()
            if time_since_last_claim < 24 * 60 * 60:  # 24 jam dalam detik
                print(f"Wallet {wallet_address} masih dalam cooldown. Sisa waktu: {int((24 * 60 * 60 - time_since_last_claim) / 3600)} jam.")
                with lock:
                    progress_counter[0] += 1
                    cooldown_counter[0] += 1
                    display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
                return

        # Solve captcha
        hcaptcha_token = solve_captcha(wallet_address)
        if not hcaptcha_token:
            print(f"[{wallet_address}] Failed to solve hCaptcha. Skipping...")
            with lock:
                progress_counter[0] += 1
                failed_counter[0] += 1
                display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
            return

        # Klaim faucet
        response = claim_faucet(wallet_address, hcaptcha_token, use_proxy=True)

        if response and "message" in response and response["message"] == "Claim detected via balance":
            print(f"[{wallet_address}] Wallet sudah diklaim (dari cek saldo). Updating history...")
            result_queue.put((wallet_address, current_time.isoformat()))
            with lock:
                progress_counter[0] += 1
                success_counter[0] += 1
                display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
            return

        if not response or ("message" in response and "Invalid Captcha" in response["message"]):
            print(f"[{wallet_address}] Invalid Captcha detected. Solving new Captcha...")
            hcaptcha_token = solve_captcha(wallet_address)
            if not hcaptcha_token:
                print(f"[{wallet_address}] Failed to solve new Captcha. Skipping...")
                with lock:
                    progress_counter[0] += 1
                    failed_counter[0] += 1
                    display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
                return
            response = claim_faucet(wallet_address, hcaptcha_token, use_proxy=False)

        if response and "message" in response and "wait 24 hours" in response["message"]:
            print(f"[{wallet_address}] Wallet sudah diklaim dalam 24 jam terakhir. Updating history...")
            result_queue.put((wallet_address, current_time.isoformat()))
            with lock:
                progress_counter[0] += 1
                cooldown_counter[0] += 1
                display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
            return

        if response and "message" in response and re.match(r"^0x[a-fA-F0-9]{64}$", response["message"]):
            print(f"[{wallet_address}] Klaim berhasil!")
            result_queue.put((wallet_address, current_time.isoformat()))
            with lock:
                progress_counter[0] += 1
                success_counter[0] += 1
                display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
        else:
            print(f"[{wallet_address}] Klaim gagal: {response}")
            with lock:
                progress_counter[0] += 1
                failed_counter[0] += 1
                display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)
    except Exception as e:
        print(f"[{wallet_address}] Error memproses wallet: {e}")
        with lock:
            progress_counter[0] += 1
            failed_counter[0] += 1
            display_progress(progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets)

# Fungsi untuk melakukan klaim dengan wallet yang ada (paralel)
def claim_with_existing_wallets():
    wallets = load_wallets()
    if not wallets:
        print("Tidak ada wallet untuk diklaim. Silakan generate wallet terlebih dahulu.")
        return

    total_wallets = len(wallets)
    print(f"Total wallet yang akan diproses: {total_wallets}")

    claim_history = load_claim_history()
    current_time = datetime.now()
    result_queue = Queue()  # Untuk menyimpan hasil klaim (wallet_address, timestamp)
    progress_counter = [0]  # Counter untuk melacak total wallet yang diproses
    success_counter = [0]  # Counter untuk wallet yang berhasil diklaim
    failed_counter = [0]   # Counter untuk wallet yang gagal diklaim
    cooldown_counter = [0] # Counter untuk wallet yang dalam cooldown
    lock = threading.Lock()  # Lock untuk thread-safe counter

    # Gunakan ThreadPoolExecutor untuk memparalelkan pemecahan captcha
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CAPTCHAS) as executor:
        futures = []
        for wallet_line in wallets:
            futures.append(executor.submit(
                process_wallet, wallet_line, claim_history, current_time, result_queue,
                progress_counter, success_counter, failed_counter, cooldown_counter, total_wallets, lock
            ))
        
        # Tunggu semua thread selesai
        for future in futures:
            future.result()

    # Tampilkan ringkasan akhir
    print("\n=== Ringkasan Klaim ===")
    print(f"Total Wallet: {total_wallets}")
    print(f"Berhasil: {success_counter[0]}")
    print(f"Gagal: {failed_counter[0]}")
    print(f"Cooldown: {cooldown_counter[0]}")
    print("======================\n")

    # Update claim history dari hasil klaim
    while not result_queue.empty():
        wallet_address, timestamp = result_queue.get()
        claim_history[wallet_address] = timestamp
    save_claim_history(claim_history)

# Fungsi utama
def main():
    # Jika wallet.txt belum ada, generate wallet baru
    if not os.path.exists(WALLET_FILE):
        print("File wallet.txt tidak ditemukan. Generating wallet baru...")
        num_accounts = int(input("Masukkan jumlah akun yang ingin dibuat: "))
        for i in range(num_accounts):
            account = w3.eth.account.create()
            wallet_address = account.address
            private_key = account._private_key.hex()
            with open(WALLET_FILE, "a") as f:
                f.write(f"{wallet_address} - {private_key}\n")
            print(f"Generated Address {i + 1}: {wallet_address}")

    # Loop untuk klaim setiap 24 jam
    while True:
        print(f"\n[{datetime.now()}] Mulai siklus klaim...")
        claim_with_existing_wallets()
        
        # Selalu jalankan send.py setelah siklus klaim
        print("Siklus klaim selesai. Menjalankan transfer saldo...")
        try:
            result = subprocess.run(["python3", "send.py"], check=True, capture_output=True, text=True)
            print(f"send.py output: {result.stdout}")
            if result.stderr:
                print(f"send.py error: {result.stderr}")
        except subprocess.CalledProcessError as e:
            print(f"Error menjalankan send.py: {e}")
            print(f"Output: {e.output}")
        except Exception as e:
            print(f"Error menjalankan send.py: {e}")

        print("Menunggu 24 jam untuk siklus berikutnya...")
        time.sleep(24 * 60 * 60)  # Jeda 24 jam

if __name__ == "__main__":
    main()
