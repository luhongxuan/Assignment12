import pandas as pd
import matplotlib.pyplot as plt

# 讀 Excel 檔（改成你的檔名）
df = pd.read_excel("seat_metric.xlsx")

# 只保留我們要的欄位，並確保 Duration_s 是數值
df = df[["Role", "Mode", "Duration_s"]].copy()
df["Duration_s"] = pd.to_numeric(df["Duration_s"], errors="coerce")
df = df.dropna(subset=["Duration_s"])

# 如果你只想看 guest，可以加這行
# df = df[df["Role"] == "guest"]

# 計算各 Mode 的平均停留時間
mean_by_mode = df.groupby("Mode")["Duration_s"].mean()
auto_mean = mean_by_mode.get("auto", float("nan"))
manual_mean = mean_by_mode.get("manual", float("nan"))
diff_manual_auto = manual_mean - auto_mean

print("=== 平均停留時間（秒） ===")
print(mean_by_mode)
print()
print(f"manual - auto 的時間差：約 {diff_manual_auto:.3f} 秒")

# 畫平均停留時間的長條圖
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(mean_by_mode.index, mean_by_mode.values)
ax.set_xlabel("Mode")
ax.set_ylabel("Average Duration (s)")
ax.set_title("Average Seat Page Duration by Mode")

# 在柱子上標數值
for i, v in enumerate(mean_by_mode.values):
    ax.text(i, v, f"{v:.2f}", ha="center", va="bottom")

plt.tight_layout()
plt.show()

# 如果想再畫一張盒鬚圖比較分布：
fig2, ax2 = plt.subplots(figsize=(8, 4))
df.boxplot(column="Duration_s", by="Mode", ax=ax2)
ax2.set_title("Seat Page Duration Distribution by Mode")
ax2.set_ylabel("Duration (s)")
plt.suptitle("")  # 移除預設標題
plt.tight_layout()
plt.show()
