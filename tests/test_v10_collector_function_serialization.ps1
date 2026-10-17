# Production Collector function provider vs parsed-AST text parity.
# Reads repository source only; no jobs, ports or OWNER state.
param([string]$Source = "")
$ErrorActionPreference = "Stop"
if (-not $Source) {
 $Source = Join-Path (Split-Path $PSScriptRoot -Parent) "ms2_live\MS2_RSS_100_Collector.ps1"
}
if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "COLLECTOR_FIXTURE_MISSING" }
$names = @("Get-NormalizedLocalWorkbookPath","Get-CollectorFileIdentityType",
 "Test-SameCanonicalWorkbookFile","Get-PublishedWorkbookGate")
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($null -eq $tree -or $errors.Count -ne 0) { throw "COLLECTOR_PARSE_FAILED" }
$astText="";$runtimeText="";$matches=@{}
foreach ($name in $names) {
 $hits=@($tree.FindAll({
    param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $names -ccontains $node.Name
 },$true) | Where-Object { $_.Name -ceq $name })
 if($hits.Count -ne 1){throw "COLLECTOR_FUNCTION_COUNT_MISMATCH"}
 $node=$hits[0]
 # Dot-source only each function declaration into this disposable CI scope; never call its body.
 $definition=[scriptblock]::Create($node.Extent.Text)
 . $definition
 $fromDisk=$node.Body.GetScriptBlock().ToString()
 $fromRuntime=(Get-Item ("function:" + $name) -ErrorAction Stop).ScriptBlock.ToString()
 $astText+="function "+$name+" {`r`n"+$fromDisk+"`r`n}`r`n"
 $runtimeText+="function "+$name+" {`r`n"+$fromRuntime+"`r`n}`r`n"
 $matches[$name]=[string]::Equals($fromRuntime,$fromDisk,[StringComparison]::Ordinal)
}
function Normalize-Newlines([string]$Text) { return (($Text -replace "`r`n","`n") -replace "`r","`n") }
$exact=[string]::Equals($runtimeText,$astText,[StringComparison]::Ordinal)
$newlinesEqual=[string]::Equals((Normalize-Newlines $runtimeText),(Normalize-Newlines $astText),[StringComparison]::Ordinal)
Write-Output ("COLLECTOR_SOURCE_PARITY="+$(if($exact){"EXACT"}elseif($newlinesEqual){"NEWLINES_ONLY"}else{"CONTENT_MISMATCH"}))
foreach($name in $names){Write-Output ("FUNCTION_"+$name.Replace("-","_").ToUpperInvariant()+"="+$(if($matches[$name]){"EXACT"}else{"MISMATCH"}))}
if(-not $exact){throw "COLLECTOR_PRODUCTION_FUNCTION_SERIALIZATION_MISMATCH"}
