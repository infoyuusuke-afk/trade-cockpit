# PS5.1 orchestration. Timed offer is Python, NOT a native PS Watcher adapter.
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'PS51_REQUIRED' }
$launch = [Diagnostics.Stopwatch]::StartNew()
python -m tests.ms2_isolated_benchmark --output isolated-latency-windows.json
if ($LASTEXITCODE -ne 0) { throw 'PYTHON_BENCHMARK_FAILED' }
@{ ps_version=$PSVersionTable.PSVersion.ToString(); runtime='Python ingress'; ps_native_producer='NOT_VERIFIED'; total_harness_ms=$launch.Elapsed.TotalMilliseconds } | ConvertTo-Json -Compress
