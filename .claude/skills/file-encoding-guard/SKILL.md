# file-encoding-guard

防乱码守卫 — 所有文件读写操作前自动触发。

## 触发场景

写入或修改任何 `.py`/`.md`/`.sh`/`.json`/`.yml`/`.toml`/`.css` 文件时。

## 根因

Windows PowerShell 5.1 默认编码是 GBK (gb2312)，`Get-Content`/`Set-Content`/`Out-File` 默认用系统编码而非 UTF-8。`>` 重定向也会用 UTF-16。这是本项目反复出现乱码的根本原因。

## 硬规则

### ❌ 禁止的写法（会引入 BOM 或乱码）

```powershell
# 以下全部禁止：
Get-Content file.py | ...                    # 默认 GBK 读取
Set-Content -Path file.py -Value $content    # 默认 UTF-16 或 BOM
"text" | Out-File file.py                    # 默认 UTF-16
$content > file.py                           # 默认 UTF-16
```

### ✅ 正确的写法

**读文件（二进制安全，不受控制台编码影响）：**
```powershell
# 方法1：指定 UTF8 编码读取
Get-Content file.py -Encoding UTF8

# 方法2：原始字节（最可靠）
$bytes = [System.IO.File]::ReadAllBytes("file.py")
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
```

**写文件（UTF-8 无 BOM + LF 行尾）：**
```powershell
# 唯一推荐方式：UTF8Encoding($false) = 无 BOM
$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("file.py", $content, $utf8NoBOM)
```

**批量 CRLF → LF 转换：**
```powershell
Get-ChildItem -Recurse -Filter *.py | ForEach-Object {
    $c = [System.IO.File]::ReadAllText($_.FullName)
    $c = $c -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($_.FullName, $c, (New-Object System.Text.UTF8Encoding $false))
}
```

### Node REPL 写文件（替代方案）

如果用 `node_repl` MCP 工具操作文件，`fs.writeFileSync(path, content, 'utf-8')` 默认就是 UTF-8 无 BOM，安全。

### apply_patch 工具

`apply_patch` 工具本身是编码安全的，直接用它编辑文件不会引入乱码。

## 验证清单

修改文件后，验证：
```powershell
# 1. 无 BOM
$bytes = [System.IO.File]::ReadAllBytes("file.py")
$bytes[0] -eq 0xEF  # 应为 False

# 2. 中文可读
Get-Content file.py -Encoding UTF8 | Select-Object -First 5

# 3. 行尾为 LF
([System.IO.File]::ReadAllText("file.py") -match "`r`n")  # 应为 False

# 4. Python 编译通过
python -m py_compile file.py
```

## .editorconfig + .gitattributes 已强制

项目根目录的 `.editorconfig`（编辑器层）和 `.gitattributes`（Git 层）已配置：
- `charset = utf-8`
- `*.py text eol=lf` / `*.sh text eol=lf`

这两个文件是防线，但 AI agent 用命令行操作时仍需遵守上述硬规则。