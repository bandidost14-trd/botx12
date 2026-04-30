# BotX12.1 Pro - Windows Setup

## Ringkasan
Proyek ini adalah bot trading Binance Futures yang menggunakan Python. Dokumen ini fokus pada cara menjalankan di Windows, tanpa mengubah logika utama bot.

## File penting
- `main_x12.py` — entry point utama bot
- `config_x12.py` — isi API key, secret, dan Telegram token/chat ID
- `requirements.txt` — dependency Python yang dibutuhkan

## Setup Windows
1. Buka PowerShell di folder `c:\botx12v2_final`
2. Buat virtual environment:
   ```powershell
   python -m venv .venv
   ```
3. Aktifkan virtual environment:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
4. Upgrade pip:
   ```powershell
   python -m pip install --upgrade pip
   ```
5. Install dependency:
   ```powershell
   python -m pip install -r requirements.txt
   ```

## Konfigurasi Auth
Set kredensial lewat environment variable, bukan ditulis langsung ke repo:
```powershell
$env:BINANCE_API_KEY="isi_api_key"
$env:BINANCE_API_SECRET="isi_api_secret"
$env:TELEGRAM_TOKEN="isi_telegram_bot_token"
$env:TELEGRAM_CHAT_ID="isi_chat_id"
```

Default bot memakai Binance Futures testnet. Untuk live:
```powershell
$env:TESTNET="0"
```

Untuk backtest tanpa Binance auth:
```powershell
$env:BACKTEST_MODE="1"
```

Jangan commit nilai sensitif ini ke repo.

## Menjalankan bot
Setelah environment aktif dan konfigurasi diisi:
```powershell
python main_x12.py
```

## File Linux-only / tidak dipakai di Windows
File ini tidak dibutuhkan jika digunakan di Windows:
- `botx12.service` — systemd service file untuk Linux
- `download_backtest_data (1).sh` — shell script Linux/WSL
- `DEPLOY_GUIDE.txt` — panduan deploy Linux/VPS dan systemd

## Catatan
- Jangan ubah logika bot utama tanpa izin.
- `requirements.txt` sudah dirapikan untuk dependency yang dipakai.
- `config_x12.py` adalah konfigurasi utama dan harus diisi manual.
