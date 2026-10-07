# Christy P 官方 LINE：雙語歡迎過渡版

本版本保留簽章驗證的 LINE Webhook，**僅在新好友加入（FollowEvent）時送出一則經核准的中英文歡迎訊息**，文案位於 `welcome_message.txt`。一般文字、六格選單點擊、AI 聊天及早安廣播仍維持靜默；舊品牌關鍵字不會回覆。六格圖文選單由 LINE Messaging API 管理，不由 Flask 伺服器產生。

## 六格選單（圖片已由使用者提供）

| 位置 | 名稱 | 暫時行為 |
|---|---|---|
| 左上 | 認識 IP／官網 | 靜默 postback，待正式網站連結與文案 |
| 上中 | 作品系列 | 靜默 postback，待作品資料 |
| 右上 | 周邊新品 | 靜默 postback，待發行品項與售價 |
| 左下 | 展覽與檔期 | 靜默 postback，待公開活動日期 |
| 下中 | 購買據點 | 靜默 postback，待藝廊／通路資訊 |
| 右下 | 合作洽詢 | 靜默 postback，待正式合作方式 |

部署時設定 `LINE_CHANNEL_SECRET` 和 `LINE_CHANNEL_ACCESS_TOKEN` 環境變數；`/callback` 驗證 LINE 的 `X-Line-Signature` 後，只在 FollowEvent 使用 LINE reply API 回覆一則 `welcome_message.txt`。`GET /health` 回 `OK`，`GET /status` 回報 `welcome_only`。LINE 官方帳號管理後台若另有原生歡迎訊息，應關閉以免重複。舊品牌程式與選單已另外封存並交付。若未來恢復其他回覆或排程，應依新品牌內容重新審核，**不要直接啟用舊版程式**。
