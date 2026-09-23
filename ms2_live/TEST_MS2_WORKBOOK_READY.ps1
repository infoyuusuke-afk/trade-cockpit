$ErrorActionPreference = 'Stop'
try {
    $excel = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')
    foreach ($book in $excel.Workbooks) {
        if ($book.Name -like 'Kioxia_MS2_RSS_Live_Signals*.xlsx') { exit 0 }
        try { if ($null -ne $book.Worksheets.Item('DASHBOARD')) { exit 0 } } catch {}
    }
    Write-Host 'MS2 RSS workbook is not open in Excel.' -ForegroundColor Yellow
} catch {
    Write-Host 'Excel is not available for the MS2 collector.' -ForegroundColor Yellow
}
exit 1
