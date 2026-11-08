"""Build research reports and suggested risk levels."""
from datetime import datetime
def build_levels(tech):
    if not tech:return None
    price=tech["current_price"];support=tech.get("support",price*.95)
    stop=round(support*.98,2);t1=round(price*1.05,2);t2=round(price*1.10,2)
    risk=price-stop;reward=t1-price
    return {"entry_zone":f"{round(support,2)} - {price}","stop_loss":stop,"target1":t1,"target2":t2,"risk_reward_ratio":round(reward/risk,2) if risk>0 else None}
def verdict_for_score(score):
    if score>=70:return "Watch closely — strong candidate on this model"
    if score>=55:return "Watchlist — verify before entry"
    return "Weak setup — does not meet the bar"
def build_markdown_report(ranked_results,as_of=None):
    as_of=as_of or datetime.now().strftime("%Y-%m-%d %H:%M IST")
    lines=[f"# Top Gainers Research Report — {as_of}","","> Automated screen, not investment advice. Verify independently. No stock is a guaranteed winner.",""]
    if not ranked_results:
        lines.append("**No candidates met the minimum bar today. Recommendation: NO BUY.**");return "\n".join(lines)
    for i,r in enumerate(ranked_results,1):
        sym,score=r["symbol"],r["total_score"];tech=r.get("tech",{});levels=build_levels(tech) if tech else None
        lines += [f"## {i}. {sym} — Score: {score}/100",f"**Verdict:** {verdict_for_score(score)}",""]
        if levels:lines += [f"- Current price: ₹{tech['current_price']}",f"- Suggested entry zone: ₹{levels['entry_zone']}",f"- Stop-loss: ₹{levels['stop_loss']}",f"- Target 1 / Target 2: ₹{levels['target1']} / ₹{levels['target2']}",f"- Risk/reward ratio: {levels['risk_reward_ratio']}",""]
        lines.append("**Why it scored this way:**")
        for cat,data in r["breakdown"].items():
            if data["notes"]:lines.append(f"- *{cat.title()}* ({data['points']} pts): "+"; ".join(data["notes"]))
        lines.append("")
    lines += ["---","Position size and final decision are yours. Reassess if the thesis changes."]
    return "\n".join(lines)
def build_telegram_message(ranked_results,as_of=None):
    as_of=as_of or datetime.now().strftime("%Y-%m-%d %H:%M")
    if not ranked_results:return f"📊 Stock Screen {as_of}\n\nNo candidates met the bar today. NO BUY."
    msg=[f"📊 Top {len(ranked_results)} Candidates — {as_of}\n"]
    for i,r in enumerate(ranked_results,1):
        levels=build_levels(r.get("tech",{})) if r.get("tech") else None
        msg.append(f"{i}. {r['symbol']} — Score {r['total_score']}/100")
        if levels:msg.append(f"   Entry: ₹{levels['entry_zone']} | SL: ₹{levels['stop_loss']} | T1: ₹{levels['target1']}")
    msg.append("\n⚠️ Research screen, not financial advice. Verify before acting.")
    return "\n".join(msg)
