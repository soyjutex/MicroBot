import json, time, os
while True:
    try:
        stats = {'cpu': 10, 'ram': 20, 'disk': 30, 'temp': 40, 'sys_log': 'log', 'bot_log': 'log'}
        with open('/home/jutex/stats.json', 'w') as f:
            json.dump(stats, f)
    except: pass
    time.sleep(2)
