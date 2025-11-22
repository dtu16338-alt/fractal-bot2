import os
import requests
import time
from playwright.sync_api import sync_playwright
# 引入 timedelta, timezone 用于时区操作
from datetime import datetime, timedelta, timezone 

# === 配置 ===
WALLET = os.environ.get("WALLET_ADDRESS")
WEBHOOK = os.environ.get("FEISHU_WEBHOOK")

# 爬虫目标URL
TARGET_URL = f"https://inswap.cc/swap/assets/{WALLET}"
TARGET_SELECTOR = "tbody" 
STATE_FILE = "last_asset_tx_id.txt"

# === 监控特定地址后缀 ===
TARGET_TO_SUFFIX = "ujxxs"
# 定义 UTC+8 时区对象
TZ_UTC_PLUS_8 = timezone(timedelta(hours=8))

# --- 状态管理函数 (不变) ---
def read_last_txid():
    """从文件中读取上次记录的交易ID"""
    try:
        with open(STATE_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

def write_last_txid(tx_id):
    """写入最新的交易ID"""
    try:
        with open(STATE_FILE, 'w') as f:
            f.write(tx_id)
        print(f"写入新状态: {tx_id}")
    except Exception as e:
        print(f"写入状态文件失败: {e}")

# --- 飞书通知函数 (不变) ---
def send_feishu(tx_data):
    """发送飞书通知"""
    if not WEBHOOK:
        print("❌ 错误: 未配置飞书 Webhook")
        return

    display_id = tx_data.get('tx_id')
    if " " in display_id: 
        display_id = display_id.split(' ')[0] + "..."

    title = f"🚨 Fractal 资产变动提醒 - {tx_data.get('asset_name', 'N/A')}"
    
    content = f"""
Tick (资产名): {tx_data.get('asset_name', 'N/A')}
金额 (Amount): {tx_data.get('amount', 'N/A')}
类型: {tx_data.get('type', 'Internal Transfer')}
---
From (发送方): {tx_data.get('from', 'N/A')}
To (接收方): {tx_data.get('to', 'N/A')}
时间 (Time): {tx_data.get('time', 'N/A')}

[点击查看详情]({tx_data.get('tx_link', TARGET_URL)})
    """
    
    data = {
        "msg_type": "text",
        "content": {
            "text": title + "\n" + content
        }
    }

    try:
        headers = {'Content-Type': 'application/json'}
        requests.post(WEBHOOK, json=data, headers=headers)
        print(f"✅ 飞书推送已发送: {display_id}")
    except Exception as e:
        print(f"推送失败: {e}")

# --- main 函数 (最终版本) ---
def main():
    if not WALLET:
        print("❌ 错误: 无法读取 WALLET_ADDRESS，请检查 GitHub Secrets 设置！")
        exit(1) 
        
    print(f"正在监控资产地址: {WALLET}")
    print("目标URL (Playwright):", TARGET_URL)
    
    last_tx_id = read_last_txid()
    print(f"上次记录的交易ID: {last_tx_id if last_tx_id else '无'}")
    
    try:
        # Playwright 启动和点击逻辑
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            print("浏览器已启动，正在访问页面...")
            page.goto(TARGET_URL, timeout=60000) 

            page.wait_for_load_state("networkidle")
            
            try:
                page.click('text="Internal Transfer"', timeout=10000)
                print("✅ 成功点击 'Internal Transfer' 标签。")
            except Exception as e:
                print(f"❌ 警告：未找到或无法点击 'Internal Transfer' 标签，可能已默认选中。")

            page.wait_for_selector(TARGET_SELECTOR, timeout=15000) 
            page.wait_for_load_state("networkidle") 
            
            print("✅ 表格加载完毕，开始 Playwright 提取。")

            # === Playwright 提取和解析逻辑 ===
            row_locators = page.locator('tbody tr').all()
            print(f"DEBUG: Playwright 找到 {len(row_locators)} 行数据。")
            
            new_transactions = []
            found_latest_tx = None
            
            for row_locator in row_locators:
                
                try:
                    asset_name_col1 = row_locator.locator('td:nth-child(1)').inner_text().strip()
                    amount_full = row_locator.locator('td:nth-child(2)').inner_text().strip()
                    from_addr = row_locator.locator('td:nth-child(3)').inner_text().strip()
                    to_addr = row_locator.locator('td:nth-child(4)').inner_text().strip()
                    # 提取原始时间字符串
                    tx_time_str_raw = row_locator.locator('td:nth-child(5)').inner_text().strip() 
                except Exception:
                    continue 
                
                # --- 状态 ID 核心修复：使用原始时间构造 ID ---
                clean_id_time = tx_time_str_raw # 使用原始字符串作为 ID 的时间部分
                
                # --- 修复逻辑：时区转换 (仅用于显示) ---
                tx_time_str_display = tx_time_str_raw
                try:
                    # 解析原始时间字符串 (格式: '11/21/2025, 9:25:00 AM')
                    dt_obj_naive = datetime.strptime(tx_time_str_raw, '%m/%d/%Y, %I:%M:%S %p')
                    
                    # 假设原始时间是 UTC 时间
                    dt_obj_utc = dt_obj_naive.replace(tzinfo=timezone.utc)
                    
                    # 转换到 UTC+8
                    dt_obj_utc8 = dt_obj_utc.astimezone(TZ_UTC_PLUS_8)
                    
                    # 重新格式化为显示格式
                    tx_time_str_display = dt_obj_utc8.strftime('%Y/%m/%d %H:%M:%S (UTC+8)')
                except ValueError:
                    print(f"DEBUG TIME: 时间字符串 '{tx_time_str_raw}' 解析失败，保留原始格式。")
                    pass
                # ----------------------------------------
                
                # --- 修复逻辑：从 Amount 列中分离 Tick 和 Amount ---
                asset_name = asset_name_col1
                if '\n' in amount_full:
                    parts = amount_full.split('\n', 1) 
                    if len(parts) == 2:
                        amount_full = parts[0].strip()
                        asset_name = parts[1].strip() 
                
                if asset_name_col1 in ['No data', '']:
                     pass 
                
                if not asset_name and not amount_full:
                    print("DEBUG PARSE: 提取结果为空，跳过此行。")
                    continue
                # ----------------------------------------------------

                # --- 核心新增：To 地址过滤 ---
                if not to_addr.endswith(TARGET_TO_SUFFIX):
                    # 即使不匹配，也要记录这个 ID，以防下次重复抓取
                    if not found_latest_tx:
                         found_latest_tx = clean_id_time + " " + asset_name
                    continue 
                # ------------------------------

                # --- DEBUG: 检查提取结果 ---
                print(f"DEBUG PARSE: Tick='{asset_name}', Amount='{amount_full}', Time='{tx_time_str_display}', To='{to_addr}' (MATCHED)")
                # --------------------------

                # 构造 ID (使用原始时间)
                tx_id = clean_id_time + " " + asset_name 
                tx_link = TARGET_URL
                
                # 检查是否是旧交易 (使用原始时间 ID)
                if last_tx_id and tx_id == last_tx_id:
                    print(f"已达到上次记录的交易ID ({last_tx_id})，停止检查。")
                    break 
                    
                # 提取交易数据
                tx_data = {
                    'tx_id': tx_id,
                    'tx_link': tx_link,
                    'asset_name': asset_name,
                    'amount': amount_full,
                    'type': "Internal Transfer",
                    'time': tx_time_str_display, # 注意：这里使用格式化的显示时间
                    'from': from_addr,
                    'to': to_addr,
                }
                new_transactions.append(tx_data)
                
                if not found_latest_tx:
                    found_latest_tx = tx_id
                    
            # 4. 处理新交易
            if new_transactions:
                print(f"发现 {len(new_transactions)} 笔新交易（符合 ujxxs 过滤）。")
                for tx in reversed(new_transactions):
                    print("--- DEBUG: READY TO SEND TX ---")
                    print(tx) 
                    print("----------------------------------")
                    send_feishu(tx)
                
                # 5. 更新状态文件
                if found_latest_tx:
                    write_last_txid(found_latest_tx)
            else:
                print("未发现符合过滤条件的新交易。")
                if found_latest_tx and found_latest_tx != last_tx_id:
                     write_last_txid(found_latest_tx)

    except Exception as e:
        print(f"致命错误：Playwright 或网络操作失败: {e}")
        exit(1)


if __name__ == "__main__":
    main()
