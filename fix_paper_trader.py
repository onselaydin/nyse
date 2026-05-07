import re

with open('LiquiditySweep_BOS_FVG_System/core/paper_trader.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix escape characters in request[\"comment\"]
content = content.replace('request[\\\"comment\\\"]', 'request["comment"]')
content = content.replace('request[\\"comment\\"]', 'request["comment"]')

with open('LiquiditySweep_BOS_FVG_System/core/paper_trader.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed')
