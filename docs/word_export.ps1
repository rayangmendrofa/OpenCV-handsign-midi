param([string]$Docx, [string]$Pdf)
# Opens the document in Word (hidden), updates the table of contents and page fields,
# saves it, and exports a PDF with clickable bookmarks.
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($Docx)
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Fields.Update() | Out-Null
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }   # again, now that page numbers are final
    $doc.Save()
    # 17 = wdExportFormatPDF; CreateBookmarks 1 = from headings
    $doc.ExportAsFixedFormat($Pdf, 17, $false, 0, 0, 1, 1, 0, $true, $true, 1, $true, $true, $false)
    "pages: $($doc.ComputeStatistics(2))"
    $doc.Close()
} finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
