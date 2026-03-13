<#
.SYNOPSIS
    video-editing-skills 前置环境检查脚本（硬件 + Python）

.DESCRIPTION
    阶段 1 - 硬件检查（满足任一条件）：
      条件 A - Intel 白名单独显：Arc A770（16GB）/ Arc B580（12GB），CPU 型号不限
      条件 B - Intel iGPU 平台：MTL / LNL / ARL / PTL CPU + Intel iGPU + 内存 > 16 GB

    阶段 2 - Python 3.12.x 检查：
      若未找到 Python 3.12.x，自动尝试安装：
        方法 1：winget install Python.Python.3.12
        方法 2：下载官方安装包 python-3.12.x-amd64.exe 静默安装

    两阶段全部通过 → exit 0；任一失败 → exit 1

.NOTES
    扩展独显白名单：在 $DGPU_WHITELIST 数组中追加型号编号即可。
    指定 Python 回退版本：修改 $PYTHON_FALLBACK_VERSION 常量。
#>

# ============================================================
# 配置项
# ============================================================

# 独显白名单：只写型号编号（如 "B580"），不写 "Arc B580"
# 实际显卡名含 (TM)，如 "Intel(R) Arc(TM) B580 Graphics"，全名匹配会失败
$DGPU_WHITELIST = @("A770", "B580")
$dGpuPattern    = $DGPU_WHITELIST -join "|"

# winget 不可用时，从 python.org 下载的回退版本
$PYTHON_FALLBACK_VERSION = "3.12.9"
$PYTHON_INSTALLER_URL    = "https://www.python.org/ftp/python/$PYTHON_FALLBACK_VERSION/python-$PYTHON_FALLBACK_VERSION-amd64.exe"

# ============================================================
# 工具函数
# ============================================================

function Find-Python312 {
    <#
    .SYNOPSIS 在 PATH 中查找 Python 3.12.x，返回可用命令字符串；未找到返回 $null
    #>
    foreach ($cmd in @("python", "python3")) {
        try {
            $ver = "$(& $cmd --version 2>&1)"
            if ($ver -match "Python 3\.12\.\d+") { return $cmd }
        } catch {}
    }
    # py launcher 方式（Windows Python Launcher）
    try {
        $ver = "$(& py -3.12 --version 2>&1)"
        if ($ver -match "Python 3\.12\.\d+") { return "py -3.12" }
    } catch {}
    return $null
}

function Get-PythonVersion([string]$cmd) {
    try {
        if ($cmd -eq "py -3.12") {
            return "$(& py -3.12 --version 2>&1)".Trim()
        }
        return "$(& $cmd --version 2>&1)".Trim()
    } catch { return "unknown" }
}

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") `
              + ";" `
              + [System.Environment]::GetEnvironmentVariable("Path","User")
}

# ============================================================
# 阶段 1：硬件检查
# ============================================================
Write-Host ""
Write-Host "=== 阶段 1：Intel 硬件平台检查 ============================="

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

# CPU 平台代号（WMI 名称含 (TM)，如 "Intel(R) Core(TM) Ultra 7 155H"）
$platform = $null
if     ($cpu -match "Ultra \d+\s+1\d{2}")                                            { $platform = "MTL" }
elseif ($cpu -match "Ultra \d+\s+2\d{2}V")                                           { $platform = "LNL" }
elseif ($cpu -match "Ultra \d+\s+2\d{2}" -and $cpu -notmatch "Ultra \d+\s+2\d{2}V") { $platform = "ARL" }
elseif ($cpu -match "Ultra \d+\s+3\d{2}")                                            { $platform = "PTL" }

$hwPass = $false

if ($dgpu) {
    # 条件 A：有白名单独显，CPU 不限
    Write-Host "✅ [PASS] 条件 A - Intel 独显（白名单）：$($dgpu.Name)"
    Write-Host "ℹ️  [INFO] 独显路线：跳过 CPU 平台与内存检查"
    $hwPass = $true
} else {
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
    $hwPass = $condB
}

if (-not $hwPass) {
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "❌ 硬件检查未通过，禁止执行后续技能。"
    Write-Host ""
    Write-Host "   支持条件 A：Intel 白名单独显（$($DGPU_WHITELIST -join ' / ')）"
    Write-Host "   支持条件 B：Intel MTL/LNL/ARL/PTL CPU + Intel iGPU + 内存 > 16 GB"
    exit 1
}

Write-Host "============================================================"
Write-Host "✅ 阶段 1 通过"

# ============================================================
# 阶段 2：Python 3.12.x 检查与自动安装
# ============================================================
Write-Host ""
Write-Host "=== 阶段 2：Python 3.12.x 环境检查 ========================="

$pythonCmd = Find-Python312

if ($pythonCmd) {
    $verStr = Get-PythonVersion $pythonCmd
    Write-Host "✅ [PASS] Python 3.12：$verStr（命令：$pythonCmd）"
} else {
    Write-Host "⚠️  [WARN] 未找到 Python 3.12.x，尝试自动安装..."
    Write-Host ""
    $installed = $false

    # ── 方法 1：winget ─────────────────────────────────────
    Write-Host "  [方法 1] 尝试通过 winget 安装 Python 3.12..."
    $wingetExe = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetExe) {
        try {
            winget install Python.Python.3.12 -e --silent `
                --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ✅ winget 安装完成"
                $installed = $true
            } else {
                Write-Host "  ⚠️  winget 返回码 $LASTEXITCODE，尝试方法 2..."
            }
        } catch {
            Write-Host "  ⚠️  winget 执行异常：$_，尝试方法 2..."
        }
    } else {
        Write-Host "  ⚠️  winget 不可用，尝试方法 2..."
    }

    # ── 方法 2：官方安装包 ─────────────────────────────────
    if (-not $installed) {
        Write-Host ""
        Write-Host "  [方法 2] 下载官方安装包 Python $PYTHON_FALLBACK_VERSION ..."
        Write-Host "  URL：$PYTHON_INSTALLER_URL"
        $tmpInstaller = Join-Path $env:TEMP "python-$PYTHON_FALLBACK_VERSION-amd64.exe"
        try {
            Write-Host "  正在下载..."
            Invoke-WebRequest -Uri $PYTHON_INSTALLER_URL -OutFile $tmpInstaller -UseBasicParsing
            Write-Host "  正在静默安装（InstallAllUsers=1 PrependPath=1）..."
            $proc = Start-Process -FilePath $tmpInstaller `
                -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" `
                -Wait -PassThru
            Remove-Item $tmpInstaller -Force -ErrorAction SilentlyContinue
            if ($proc.ExitCode -eq 0) {
                Write-Host "  ✅ 官方安装包安装完成"
                $installed = $true
            } else {
                Write-Host "  ❌ 安装包返回码：$($proc.ExitCode)"
            }
        } catch {
            Remove-Item $tmpInstaller -Force -ErrorAction SilentlyContinue
            Write-Host "  ❌ 下载或安装失败：$_"
        }
    }

    # ── 刷新 PATH 并重新检测 ───────────────────────────────
    if ($installed) {
        Write-Host ""
        Write-Host "  刷新 PATH 并重新检测 Python 3.12..."
        Refresh-Path
        $pythonCmd = Find-Python312
    }

    if ($pythonCmd) {
        $verStr = Get-PythonVersion $pythonCmd
        Write-Host "✅ [PASS] Python 3.12 安装成功：$verStr（命令：$pythonCmd）"
    } else {
        Write-Host ""
        Write-Host "❌ [FAIL] Python 3.12.x 安装后仍未检测到。"
        Write-Host "   请关闭当前终端后重新打开，或手动安装："
        Write-Host "   https://www.python.org/downloads/release/python-3129/"
        Write-Host "   安装时勾选 'Add Python to PATH' 并选择 'Install for all users'"
        exit 1
    }
}

Write-Host "============================================================"
Write-Host ""
Write-Host "✅ 所有检查通过（硬件 + Python 3.12），可执行后续技能。"
exit 0
