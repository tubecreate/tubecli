---
description: Push code and bump version with timestamp format year.month.day.hourminutesecond
---
// turbo-all
1. Get current UTC+0 datetime and format it as version string `YYYY.MM.DD.HHmmss`
```powershell
$ver = [DateTime]::UtcNow.ToString("yyyy.MM.dd.HHmmss")
Write-Host "New version: $ver"
```

2. Update `tubecli/__init__.py` with the new version
```powershell
$content = Get-Content "C:\tubecreate-vue\tubecli\tubecli\__init__.py" -Raw
$newContent = $content -replace '__version__ = ".*"', "__version__ = `"$ver`""
Set-Content "C:\tubecreate-vue\tubecli\tubecli\__init__.py" -Value $newContent -NoNewline
```

3. Update `server_code/api/market-cli/version.json` with the new version and changelog from user input  
   (Edit the changelog field manually with what changed, then run steps below)

4. Stage all changes and commit with version tag
```powershell
cd C:\tubecreate-vue\tubecli ; git add . ; git commit -m "release: v$ver - update version and changelog"
```

5. Push to remote
```powershell
cd C:\tubecreate-vue\tubecli ; git push
```

6. Push server_code to remote (if separate repo)
```powershell
cd C:\tubecreate-vue ; git add server_code/ ; git commit -m "release: v$ver - update version.json on server" ; git push
```
