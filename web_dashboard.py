import http.server
import socketserver
import json
import subprocess
import os
import sys
import threading
import time

PORT = 8080
bot_process = None
bot_lock = threading.Lock()

def start_bot():
    global bot_process
    with bot_lock:
        if bot_process is not None and bot_process.poll() is None:
            return False, "Bot is already running."
        try:
            # Khởi chạy auto_ping.py ở chế độ unbuffered
            bot_process = subprocess.Popen(
                [sys.executable, "-u", "auto_ping.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Đọc logs bất đồng bộ từ stdout và ghi vào file bot.log
            def log_reader(proc):
                for line in proc.stdout:
                    try:
                        with open("bot.log", "a", encoding="utf-8") as f:
                            f.write(line)
                    except Exception:
                        pass
                    # In ra stdout của server để dễ debug
                    sys.stdout.write(line)
                    sys.stdout.flush()
            
            threading.Thread(target=log_reader, args=(bot_process,), daemon=True).start()
            return True, "Bot started successfully."
        except Exception as e:
            return False, f"Failed to start bot: {str(e)}"

def stop_bot():
    global bot_process
    with bot_lock:
        if bot_process is None or bot_process.poll() is not None:
            bot_process = None
            return False, "Bot is not running."
        try:
            bot_process.terminate()
            bot_process.wait(timeout=3)
            bot_process = None
            return True, "Bot stopped successfully."
        except subprocess.TimeoutExpired:
            try:
                bot_process.kill()
            except Exception:
                pass
            bot_process = None
            return True, "Bot force killed."
        except Exception as e:
            return False, f"Failed to stop bot: {str(e)}"

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Tắt log mặc định để tránh làm rối console
        return

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.get_html().encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(self.get_status()).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/api/start":
            success, msg = start_bot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode("utf-8"))
        elif self.path == "/api/stop":
            success, msg = stop_bot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def get_status(self):
        global bot_process
        is_running = False
        with bot_lock:
            if bot_process is not None:
                if bot_process.poll() is None:
                    is_running = True
                else:
                    bot_process = None
        
        logs = ""
        total_sent = 0
        if os.path.exists("bot.log"):
            try:
                with open("bot.log", "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    logs = "".join(lines[-40:]) # Lấy 40 dòng logs cuối
                    for line in lines:
                        if "Gửi thành công msg" in line:
                            total_sent += 1
            except Exception:
                pass
        
        return {
            "running": is_running,
            "total_sent": total_sent,
            "did_key": "did:key:z6MkfSGt6WwnKJWU1qznQBvHYpnPJL8fsC2aRJVkS5B9yTTA",
            "room": "lobby",
            "interval": "120 giây (2 phút)",
            "logs": logs
        }

    def get_html(self):
        return """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Technocore Bot Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;700&family=Inter:wght@300;400;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; }
        .console { font-family: 'Fira Code', monospace; }
    </style>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen flex flex-col">
    <!-- Header -->
    <header class="border-b border-gray-900 bg-gray-950/80 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
        <div class="flex items-center space-x-3">
            <div class="bg-indigo-600 p-2 rounded-xl text-white shadow-lg shadow-indigo-600/30">
                <i class="fa-solid fa-robot text-xl"></i>
            </div>
            <div>
                <h1 class="text-lg font-bold tracking-tight">Agent Flop Dashboard</h1>
                <p class="text-xs text-gray-400">Technocore Integration Controller</p>
            </div>
        </div>
        <div class="flex items-center space-x-2">
            <span id="status-badge" class="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-gray-900 text-gray-400 border border-gray-800">
                <span id="status-dot" class="w-2 h-2 mr-2 rounded-full bg-gray-500"></span>
                <span id="status-text">Đang tải...</span>
            </span>
        </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 p-6 max-w-6xl w-full mx-auto grid grid-cols-1 md:grid-cols-3 gap-6">
        
        <!-- Info Cards -->
        <div class="md:col-span-1 space-y-6">
            <!-- Status Card -->
            <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl space-y-6">
                <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-400">Điều khiển</h3>
                <div class="flex flex-col space-y-3">
                    <button id="start-btn" onclick="controlBot('start')" class="w-full py-3 px-4 rounded-xl font-medium bg-emerald-600 hover:bg-emerald-500 active:scale-[0.98] transition shadow-lg shadow-emerald-900/30 disabled:opacity-40 disabled:pointer-events-none">
                        <i class="fa-solid fa-play mr-2"></i> Khởi chạy Bot
                    </button>
                    <button id="stop-btn" onclick="controlBot('stop')" class="w-full py-3 px-4 rounded-xl font-medium bg-rose-600 hover:bg-rose-500 active:scale-[0.98] transition shadow-lg shadow-rose-900/30 disabled:opacity-40 disabled:pointer-events-none">
                        <i class="fa-solid fa-stop mr-2"></i> Dừng Bot
                    </button>
                </div>
            </div>

            <!-- Stats Card -->
            <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl space-y-4">
                <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-400">Thống kê & Cấu hình</h3>
                <div class="space-y-4 pt-2">
                    <div class="flex justify-between border-b border-gray-800 pb-3">
                        <span class="text-gray-400 text-sm">Tổng tin nhắn:</span>
                        <span id="stat-total" class="font-bold text-indigo-400 text-lg">0</span>
                    </div>
                    <div class="flex justify-between border-b border-gray-800 pb-3">
                        <span class="text-gray-400 text-sm">Phòng Chat:</span>
                        <span id="stat-room" class="font-semibold text-gray-200">lobby</span>
                    </div>
                    <div class="flex justify-between border-b border-gray-800 pb-3">
                        <span class="text-gray-400 text-sm">Chu kỳ:</span>
                        <span id="stat-interval" class="font-semibold text-gray-200">120 giây</span>
                    </div>
                </div>
            </div>

            <!-- Keys Card -->
            <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl space-y-4">
                <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-400">Thông tin DID Key</h3>
                <div class="space-y-3 pt-2">
                    <div>
                        <label class="text-xs text-gray-500 block mb-1">DID Key:</label>
                        <div class="bg-gray-950 p-3 rounded-lg border border-gray-800 text-xs break-all select-all font-mono text-gray-300">
                            did:key:z6MkfSGt6WwnKJWU1qznQBvHYpnPJL8fsC2aRJVkS5B9yTTA
                        </div>
                    </div>
                    <div class="text-xs text-amber-500 bg-amber-950/20 border border-amber-900/30 p-3 rounded-xl">
                        <i class="fa-solid fa-triangle-exclamation mr-1"></i> Private key được lưu an toàn trong file .env môi trường.
                    </div>
                </div>
            </div>
        </div>

        <!-- Log & Output -->
        <div class="md:col-span-2 flex flex-col">
            <div class="bg-gray-900 border border-gray-800 rounded-2xl flex-1 flex flex-col overflow-hidden shadow-xl min-h-[500px]">
                <div class="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
                    <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-400">Bảng ghi log hoạt động</h3>
                    <div class="flex space-x-2">
                        <button onclick="updateStatus()" class="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition text-gray-400 hover:text-white" title="Làm mới">
                            <i class="fa-solid fa-arrows-rotate text-sm"></i>
                        </button>
                    </div>
                </div>
                <div id="log-container" class="flex-1 p-6 bg-gray-950 overflow-y-auto console text-xs text-emerald-400 leading-relaxed whitespace-pre-wrap">
                    Đang tải logs từ server...
                </div>
            </div>
        </div>
    </main>

    <!-- Footer -->
    <footer class="border-t border-gray-900 bg-gray-950 py-4 px-6 text-center text-xs text-gray-600">
        <p>&copy; 2026 Agent Flop Core. Live data monitored on <a href="https://technocore.chat/r/lobby" target="_blank" class="text-indigo-400 hover:underline">technocore.chat</a>.</p>
    </footer>

    <!-- Scripts -->
    <script>
        const startBtn = document.getElementById('start-btn');
        const stopBtn = document.getElementById('stop-btn');
        const statusBadge = document.getElementById('status-badge');
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        const statTotal = document.getElementById('stat-total');
        const logContainer = document.getElementById('log-container');

        let isPolling = false;

        async function updateStatus() {
            if (isPolling) return;
            isPolling = true;
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                // Cập nhật trạng thái chạy
                if (data.running) {
                    statusBadge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-950/30 text-emerald-400 border border-emerald-900/30";
                    statusDot.className = "w-2 h-2 mr-2 rounded-full bg-emerald-500 animate-pulse";
                    statusText.textContent = "Bot đang chạy";
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                } else {
                    statusBadge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-950/30 text-rose-400 border border-rose-900/30";
                    statusDot.className = "w-2 h-2 mr-2 rounded-full bg-rose-500";
                    statusText.textContent = "Bot đang dừng";
                    startBtn.disabled = false;
                    stopBtn.disabled = true;
                }

                // Cập nhật thống kê
                statTotal.textContent = data.total_sent;
                
                // Cập nhật log
                if (data.logs) {
                    const shouldScroll = logContainer.scrollHeight - logContainer.clientHeight <= logContainer.scrollTop + 50;
                    logContainer.textContent = data.logs;
                    if (shouldScroll) {
                        logContainer.scrollTop = logContainer.scrollHeight;
                    }
                } else {
                    logContainer.textContent = "Chưa có log ghi nhận. Hãy khởi chạy Bot!";
                }
            } catch (err) {
                console.error("Lỗi khi tải thông tin:", err);
            } finally {
                isPolling = false;
            }
        }

        async function controlBot(action) {
            try {
                if (action === 'start') {
                    startBtn.disabled = true;
                    logContainer.textContent = "Đang khởi động Bot...";
                } else {
                    stopBtn.disabled = true;
                    logContainer.textContent = "Đang tắt Bot...";
                }
                const response = await fetch(`/api/${action}`, { method: 'POST' });
                const result = await response.json();
                await updateStatus();
                alert(result.message);
            } catch (err) {
                alert(`Lỗi thực thi lệnh: ${err}`);
            }
        }

        // Tự động tải thông tin mỗi 2 giây
        updateStatus();
        setInterval(updateStatus, 2000);
    </script>
</body>
</html>"""

if __name__ == "__main__":
    # Tự khởi động bot luôn khi mở server
    print("🚀 Khởi chạy Web Dashboard...")
    start_bot()
    
    # Chạy HTTP Server
    with socketserver.TCPServer(("", PORT), DashboardHandler) as httpd:
        print(f"🌍 Dashboard đã sẵn sàng tại: http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping dashboard server...")
            stop_bot()
            sys.exit(0)
