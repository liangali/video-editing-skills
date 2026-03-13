<#
.SYNOPSIS
    Intel 硬件平台兼容性检查脚本
    用于 video-editing-skills 技能的前置门控检查

.DESCRIPTION
    满足以下任一条件则通过（exit 0），否则终止（exit 1）：
      条件 A - Intel 白名单独显：Arc A770（16GB）/ Arc B580（12GB），CPU 型号不限
      条件 B - Intel iGPU 平台：MTL / LNL / ARL / PTL CPU + Intel iGPU + 内存 > 16 GB

.NOTES
    如需扩展独显白名单，在 $DGPU_WHITELIST 数组中追加型号关键字即可。
#>

# ────────────────────────────────────────────────────────────
# 配置：独显白名单（VRAM >= 12 GB 的 Intel Arc 型号编号）
# 只写型号编号（如 "B580"），不写 "Arc B580"，
# 因为实际显卡名为 "Intel(R) Arc(TM) B580 Graphics"，含 (TM) 导致全名匹配失败。
# ────────────────────────────────────────────────────────────
$DGPU_WHITELIST = @("A770", "B580")
$dGpuPattern    = $DGPU_WHITELIST -join "|"

# ────────────────────────────────────────────────────────────
# 采集硬件信息
# ────────────────────────────────────────────────────────────
$cpu        = (Get-WmiObject Win32_Processor).Name
$allGpus    = Get-WmiObject Win32_VideoController
$totalMemGB = [math]::Round((Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)

# 独显：名称匹配白名单
$dgpu = $allGpus |
    Where-Object { $_.Name -match "Intel" -and $_.Name -match $dGpuPattern } |
    Select-Object -First 1

# iGPU：Intel 集成显卡，排除白名单独显
$igpu = $allGpus |
    Where-Object {
        $_.Name -match "Intel" -and
        $_.Name -match "UHD|Iris|Xe|Arc" -and
        $_.Name -notmatch $dGpuPattern
    } |
    Select-Object -First 1

# CPU 平台代号
# 实际 WMI 名称格式：Intel(R) Core(TM) Ultra <档位> <型号><后缀>
# 例如："Intel(R) Core(TM) Ultra 7 155H" / "Intel(R) Core(TM) Ultra 9 285K"
# 旧写法 "Core Ultra [1]\d{2}" 有两个问题：
#   1. Core 和 Ultra 之间有 (TM)，字面 "Core Ultra" 无法匹配
#   2. 缺少档位数字（5/7/9），型号数字位置错位
# 修复：改为 "Ultra \d+\s+<型号前缀>" 跳过档位数字和 (TM)
$platform = $null
if     ($cpu -match "Ultra \d+\s+1\d{2}")                                            { $platform = "MTL" }  # 1xx：165H/155H/125H 等
elseif ($cpu -match "Ultra \d+\s+2\d{2}V")                                           { $platform = "LNL" }  # 2xxV：258V/288V 等
elseif ($cpu -match "Ultra \d+\s+2\d{2}" -and $cpu -notmatch "Ultra \d+\s+2\d{2}V") { $platform = "ARL" }  # 2xx（非V）：285K/285H/265K 等
elseif ($cpu -match "Ultra \d+\s+3\d{2}")                                            { $platform = "PTL" }  # 3xx：未来 PTL 型号

# ────────────────────────────────────────────────────────────
# 条件判断
# ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Intel 平台兼容性检查 ==================================="

# 条件 A：白名单独显（CPU 不限）
if ($dgpu) {
    Write-Host "✅ [PASS] 条件 A - Intel 独显（白名单）：$($dgpu.Name)"
    Write-Host "ℹ️  [INFO] 独显路线：跳过 CPU 平台与内存检查"
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "✅ 平台检查通过（条件 A），可执行后续技能。"
    exit 0
}

# 条件 B：MTL/LNL/ARL/PTL + iGPU + 内存 > 16 GB
Write-Host "ℹ️  [INFO] 未检测到白名单独显，检查条件 B（iGPU 平台）..."
$condB = $true

if ($platform) {
    Write-Host "✅ [PASS] CPU 平台：$platform（$cpu）"
} else {
    Write-Host "❌ [FAIL] CPU 不支持：$cpu"
    Write-Host "         需要 Intel MTL/LNL/ARL/PTL，或配备白名单独显（$($DGPU_WHITELIST -join ' / ')）"
    $condB = $false
}

if ($igpu) {
    Write-Host "✅ [PASS] Intel iGPU：$($igpu.Name)"
} else {
    Write-Host "❌ [FAIL] 未检测到 Intel iGPU"
    $condB = $false
}

if ($totalMemGB -gt 16) {
    Write-Host "✅ [PASS] 内存：${totalMemGB} GB"
} else {
    Write-Host "❌ [FAIL] 内存不足：${totalMemGB} GB（需 > 16 GB）"
    $condB = $false
}

Write-Host "============================================================"

if ($condB) {
    Write-Host ""
    Write-Host "✅ 平台检查通过（条件 B），可执行后续技能。"
    exit 0
} else {
    Write-Host ""
    Write-Host "❌ 平台检查未通过，禁止执行后续技能。"
    Write-Host ""
    Write-Host "   支持条件 A：Intel 白名单独显（$($DGPU_WHITELIST -join ' / ')）"
    Write-Host "   支持条件 B：Intel MTL/LNL/ARL/PTL CPU + Intel iGPU + 内存 > 16 GB"
    exit 1
}
