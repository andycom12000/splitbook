# SplitBook — 小團體拆帳

5 人以內互記帳務的拆帳工具。分錄式帳本（Σnet 恆為 0）、
分攤在寫入時固化、結算快照 + 部分付款對帳。

## 啟動

```bash
pip install -r splitbook/requirements.txt
# repo root:
uvicorn splitbook.main:app --reload
```

環境變數：`SPLITBOOK_DB`（預設 splitbook.db）、`SPLITBOOK_SECRET`（正式部署必改）。

## 測試

```bash
python -m pytest splitbook/tests -v
```

## 概念

見 repo root 的 `CONTEXT.md`。
