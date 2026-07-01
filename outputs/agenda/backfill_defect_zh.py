"""一次性:给演示库 panel-defect 证据补权威中文译文 ref_zh(人工翻译,不失真)。"""
import json
from pipeline import store

ZH = {
    "deepseek: Sent message to '测试助手' instead of the specified recipient '文件传输助手'":
        "把消息发给了『测试助手』,而不是指定的收件人『文件传输助手』",
    "gemini: Sent message to the wrong contact ('测试助手' instead of '文件传输助手').":
        "发错了联系人:发给了『测试助手』,应该发给『文件传输助手』。",
}


def main():
    con = store.connect(None)
    rows = con.execute("SELECT id, evidence_json FROM findings").fetchall()
    for r in rows:
        ev = json.loads(r["evidence_json"] or "null")
        if not isinstance(ev, list):
            continue
        changed = False
        for e in ev:
            if e.get("source") == "panel-defect":
                zh = ZH.get((e.get("ref") or "").strip())
                if zh and e.get("ref_zh") != zh:
                    e["ref_zh"] = zh
                    changed = True
        if changed:
            con.execute("UPDATE findings SET evidence_json=? WHERE id=?",
                        (json.dumps(ev, ensure_ascii=False), r["id"]))
            print("updated finding", r["id"])
    con.commit()

    print("--- verify ---")
    for r in con.execute("SELECT id, evidence_json FROM findings").fetchall():
        ev = json.loads(r["evidence_json"] or "null")
        for e in (ev or []):
            if e.get("source") == "panel-defect":
                print(r["id"], "| ref_zh =", e.get("ref_zh"))


if __name__ == "__main__":
    main()
