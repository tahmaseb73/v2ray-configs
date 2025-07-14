import base64
import json
import os
import random
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import pybase64
import binascii

# تنظیمات
class Setting:
    _setting = None

    @classmethod
    def read_settings(cls):
        if cls._setting is None:
            try:
                with open('appsettings.json', 'r', encoding='utf-8') as file:
                    cls._setting = json.loads(file.read())
            except FileNotFoundError:
                print("Error: appsettings.json not found")
                return {}
            except json.JSONDecodeError:
                print("Error: Invalid JSON format in appsettings.json")
                return {}
        return cls._setting

SETTINGS = Setting.read_settings()

# مدیریت محتوا
class ContentManager:
    def __init__(self):
        self.default_supersub_title = "4pm+77iPIGIybi5pci92MnJheS1jb25mIHwgU3VwZXJTdWI="

    @staticmethod
    def __get_file(file_path: str, title: str = None, default: str = None) -> str:
        try:
            with open(file_path, 'r', encoding="utf-8") as file:
                content = file.read()
                if title:
                    content = content.replace('%TITLE%', base64.b64encode(title.encode()).decode())
                elif default:
                    content = content.replace('%TITLE%', default)
            return content
        except FileNotFoundError:
            print(f"Error: File {file_path} not found")
            return ""

    def get_v2ray_supersub(self, title: str = None) -> str:
        return self.__get_file('src/contents/fixed-v2ray-supersub', title, self.default_supersub_title)

# توابع کمکی
def ensure_directories_exist():
    base_dir = os.path.abspath(os.path.join(os.getcwd(), SETTINGS.get('out_dir', 'configs')))
    output_folder = os.path.join(base_dir, "v2ray")
    os.makedirs(os.path.join(output_folder, "subs"), exist_ok=True)
    return output_folder

def decode_base64(encoded):
    decoded = ""
    for encoding in ["utf-8", "iso-8859-1"]:
        try:
            decoded = pybase64.b64decode(encoded + b"=" * (-len(encoded) % 4)).decode(encoding)
            break
        except (UnicodeDecodeError, binascii.Error):
            pass
    return decoded

def decode_files_links(links):
    decoded_data = []
    for link in links:
        try:
            response = requests.get(f"https://raw.githubusercontent.com/{link}", timeout=SETTINGS.get('timeout', 5))
            encoded_bytes = response.content
            decoded_text = decode_base64(encoded_bytes)
            decoded_data.append(decoded_text)
        except requests.RequestException:
            pass
    return decoded_data

def decode_dirs_links(links):
    decoded_dir_links = []
    for link in links:
        try:
            response = requests.get(f"https://raw.githubusercontent.com/{link}", timeout=SETTINGS.get('timeout', 5))
            decoded_text = response.text
            decoded_dir_links.append(decoded_text)
        except requests.RequestException:
            pass
    return decoded_dir_links

# تست پینگ
class V2RayPingTester:
    def __init__(self, configs, timeout=5, max_threads=100):
        self.configs = configs
        self.timeout = timeout
        self.max_threads = max_threads

    def parse_config(self, config):
        try:
            if config.startswith(('vmess://', 'vless://', 'trojan://', 'ss://')):
                raw = config.split('://')[1]
                if str(raw).count("#") == 0:
                    decoded = base64.b64decode(raw + '==').decode('utf-8')
                else:
                    decoded = raw
                if decoded.startswith("{"):
                    json_data = json.loads(decoded)
                    host = json_data.get('add')
                    port = int(json_data.get('port', 443))
                    tls_enabled = json_data.get('tls') == 'tls'
                    return host, port, tls_enabled
                else:
                    host = (decoded.split(":")[0]).split("@")[1]
                    port = int((decoded.split(":")[1]).split("?")[0])
                    tls_enabled = True if decoded.lower().count("security=none") == 0 else False
                    return host, port, tls_enabled
            return None
        except Exception:
            return None

    def test_single(self, config):
        parsed = self.parse_config(config)
        if not parsed:
            return {'config': config, 'status': 'invalid', 'ping': None}
        host, port, use_tls = parsed
        try:
            start_time = time.time()
            sock = socket.create_connection((host, port), timeout=self.timeout)
            if use_tls:
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=host)
            sock.close()
            end_time = time.time()
            ping_ms = int((end_time - start_time) * 1000)
            return {'config': config, 'status': 'reachable', 'ping': ping_ms}
        except Exception:
            return {'config': config, 'status': 'unreachable', 'ping': None}

    def test_all(self):
        results = []
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = [executor.submit(self.test_single, config) for config in self.configs]
            for future in as_completed(futures):
                result = future.result()
                if result['status'] == 'reachable' and result['ping'] is not None:
                    results.append(result)
        sorted_results = sorted(results, key=lambda x: x['ping'] if x['ping'] is not None else float('inf'))
        return sorted_results

# اسکریپت اصلی
def generate_subscription():
    content_manager = ContentManager()
    output_folder = ensure_directories_exist()

    # دریافت منابع
    sources = SETTINGS.get('sources', {})
    files = sources.get('files', [])
    dirs = sources.get('dirs', [])

    # استخراج کانفیگ‌ها
    configs = []
    for data in decode_files_links(files):
        configs.extend(data.splitlines())
    for data in decode_dirs_links(dirs):
        configs.extend(data.splitlines())

    # حذف تکراری‌ها و شافل کردن
    configs = list(set(configs))
    configs = [config for config in configs if any(config.startswith(p) for p in SETTINGS.get('protocols', []))]
    random.shuffle(configs)

    # تست پینگ
    tester = V2RayPingTester(configs, timeout=SETTINGS.get('timeout', 5), max_threads=SETTINGS.get('max_threads', 100))
    results = tester.test_all()

    # محدود کردن به تعداد مشخص‌شده
    config_limit = SETTINGS.get('supersub_configs_limit', 10)
    configs = [res['config'] for res in results[:config_limit]]

    # تولید محتوای ساب‌اسکریپشن
    data = content_manager.get_v2ray_supersub() + "\n".join(configs)

    # ذخیره فایل
    file_path = os.path.join(output_folder, "subs", "super-sub.txt")
    with open(file_path, "w+", encoding="utf-8") as f:
        f.write(data)

    # تولید لینک Base64
    encoded_data = base64.b64encode(data.encode("utf-8")).decode("utf-8")
    subscription_link = f"https://raw.githubusercontent.com/{SETTINGS.get('raw_repo', 'username/repo')}/{SETTINGS.get('out_dir', 'configs')}/v2ray/subs/super-sub.txt"

    print(f"Subscription Link: {subscription_link}")
    print(f"Base64 Content: {encoded_data}")

if __name__ == "__main__":
    generate_subscription()
