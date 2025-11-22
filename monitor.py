import os
import requests
import time
from datetime import datetime

# === 读取配置 ===
WALLET = os.environ.get("WALLET_ADDRESS")
WEBHOOK = os.environ.get("FEISHU_WEBHOOK")

def send_feishu(tx_id, amount_sats, tx_type, tx_time_str):
    """发送飞书通知"""
    if not WEBHOOK:
        print("❌ 错误: 未配置飞书 Webhook")
        return

    amount_btc = amount_sats / 100_000_000
    title = f"🚨 Fractal 动帐提醒: {tx_type}"
    
    content = f"""
时间: {tx_time_str}
类型: {tx_type}
金额: {amount_btc} FB ({amount_sats} sats)

详情: https://mempool.fractalbitcoin.io/tx/{tx_id}
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
        print(f"✅ 飞书推送已发送: {tx_id}")
    except Exception as e:
        print(f"推送失败: {e}")

def main():
    # === 关键检查 ===
    if not WALLET:
        print("❌ 错误: 无法读取 WALLET_ADDRESS，请检查 GitHub Secrets 设置！")
        exit(1) 
        
    API_URL = f"https://mempool.fractalbitcoin.io/api/address/{WALLET}/txs"
    print(f"正在监控地址: {WALLET}")
    print("监控范围: 过去 1 小时 (3600秒)")
    
    try:
        resp = requests.get(API_URL, timeout=15)
        if resp.status_code != 200:
            print(f"API 请求失败: {resp.status_code}")
            return
        
        txs = resp.json()
        if not isinstance(txs, list):
            print(f"API 返回格式异常: {txs}")
            return
            
    except Exception as e:
        print(f"网络错误: {e}")
        return

    if not txs:
        print("无交易记录")
        return

    # === 修改处：检查最近 1 小时 (3600秒) ===
    # 为了防止边缘漏单，稍微加一点冗余，比如 3700 秒
    CHECK_WINDOW = 3700 
    now = time.time()
    has_new_tx = False

    for tx in txs:
        if not isinstance(tx, dict): continue
            
        if tx.get('status', {}).get('confirmed'):
            tx_time = tx['status']['block_time']
        else:
            tx_time = now 

        # 判断是否在 1 小时内
        if (now - tx_time) <= CHECK_WINDOW:
            balance_change = 0
            # 检查 inputs
            for vin in tx.get('vin', []):
                if vin.get('prevout') and vin['prevout'].get('scriptpubkey_address') == WALLET:
                    balance_change -= vin['prevout']['value']
            # 检查 outputs
            for vout in tx.get('vout', []):
                if vout.get('scriptpubkey_address') == WALLET:
                    balance_change += vout['value']

            if balance_change != 0:
                tx_type = "收款" if balance_change > 0 else "转出"
                tx_time_str = datetime.fromtimestamp(tx_time).strftime('%Y-%m-%d %H:%M:%S')
                
                print(f"发现新交易: {tx['txid']}")
                send_feishu(tx['txid'], balance_change, tx_type, tx_time_str)
                has_new_tx = True
    
    if not has_new_tx:
        print("过去 1 小时无新动帐")

if __name__ == "__main__":
    main()
