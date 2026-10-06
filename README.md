# Christy P 官方 LINE：靜默過渡版

本版本只保留簽章驗證的 LINE Webhook 與健康檢查。**不發送文字、貼圖、歡迎訊息、AI 聊天、早安廣播，也不處理任何舊品牌關鍵字。** 六格圖文選單由 LINE Messaging API 上傳與管理，不由 Flask 伺服器產生。

## 六格選單（圖片已由使用者提供）

| 位置 | 名稱 | 暫時行為 |
|---|---|---|
| 左上 | 認識 IP／官網 | 靜默 postback，待正式網站連結與文案 |
| 上中 | 作品系列 | 靜默 postback，待作品資料 |
| 右上 | 周邊新品 | 靜默 postback，待發行品項與售價 |
| 左下 | 展覽與檔期 | 靜默 postback，待公開活動日期 |
| 下中 | 購買據點 | 靜默 postback，待藝廊／通路資訊 |
| 右下 | 合作洽詢 | 靜默 postback，待正式合作方式 |

部署時設定 `LINE_CHANNEL_SECRET` 環境變數，供 `/callback` 驗證 LINE 的 `X-Line-Signature`；`GET /health` 回 `OK`。舊品牌程式與選單已另外封存並交付。若未來恢復回覆或排程，應依新品牌內容重新審核，**不要直接啟用舊版程式**。
