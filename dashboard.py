"""Flask dashboard reading the latest saved screening report."""
import os,json
from flask import Flask,render_template_string
app=Flask(__name__);REPORT_DIR="reports"
TEMPLATE="""<!DOCTYPE html><html><head><title>Stock Screener Dashboard</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>
body{font-family:-apple-system,sans-serif;max-width:800px;margin:40px auto;padding:0 16px;background:#0f1115;color:#e8e8e8}h1{font-size:1.4rem}.card{background:#1a1d24;border-radius:10px;padding:16px;margin-bottom:16px;border:1px solid #2a2d35}.score{font-size:1.3rem;font-weight:bold;color:#4ade80}.warn{color:#fbbf24;font-size:.85rem;margin-bottom:20px}.note{font-size:.85rem;color:#b0b0b0;margin:4px 0}.levels{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0;font-size:.9rem}.levels div{background:#0f1115;padding:6px 10px;border-radius:6px}</style></head><body>
<h1>📊 Top Gainers Screen — {{ as_of }}</h1><p class="warn">⚠️ Automated research screen, not financial advice. Verify independently.</p>
{% if not results %}<div class="card"><strong>No candidates met the bar today. Recommendation: NO BUY.</strong></div>{% endif %}
{% for r in results %}<div class="card"><h2>{{ loop.index }}. {{ r.symbol }} — <span class="score">{{ r.total_score }}/100</span></h2>
{% if r.tech %}<div class="levels"><div>Price: ₹{{ r.tech.current_price }}</div><div>RSI: {{ r.tech.rsi }}</div><div>Trend: {{ r.tech.trend }}</div></div>{% endif %}
{% for cat,data in r.breakdown.items() %}{% for n in data.notes %}<div class="note">• {{ n }}</div>{% endfor %}{% endfor %}</div>{% endfor %}</body></html>"""
@app.route("/")
def index():
    path=os.path.join(REPORT_DIR,"latest.json")
    if not os.path.exists(path):return render_template_string(TEMPLATE,as_of="No report yet",results=[])
    with open(path) as f:data=json.load(f)
    return render_template_string(TEMPLATE,as_of=data["as_of"],results=data["results"])
if __name__=="__main__":
    port=int(os.environ.get("PORT",5000));app.run(host="0.0.0.0",port=port)
