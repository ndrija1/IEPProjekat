<#
.SYNOPSIS
    Rebuild a service from its already-built image and restart it. Works with
    no internet access.

.DESCRIPTION
    The normal `docker compose build` needs the network twice: pip reaches
    PyPI, and BuildKit resolves the FROM image against the registry even when
    that image sits in the local cache. Once the network is cut, both fail.

    This script sidesteps both. It layers only the changed sources onto the
    image that was built earlier while the network was up - no pip, no
    registry lookup. Two ways of doing that, tried in order:

      1. docker build on <service>/Dockerfile.patch with the legacy builder
         (BuildKit off, so the local FROM image is taken directly)
      2. docker create + cp + commit, which uses no builder at all - the
         fallback for when the legacy builder is finally removed

.PARAMETER Service
    authentication | employee | director | public-search | all

.PARAMETER Kubernetes
    Restart the k8s deployment instead of the compose container.

.EXAMPLE
    .\patch.ps1 director
    .\patch.ps1 director -k8s
    .\patch.ps1 all -k8s
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('authentication', 'employee', 'director', 'public-search', 'all')]
    [string] $Service,

    [Alias('k8s')]
    [switch] $Kubernetes
)

# NOT 'Stop': docker writes ordinary notices (e.g. the legacy-builder
# deprecation warning) to stderr, and PowerShell 5.1 turns those into
# terminating errors. Exit codes are checked explicitly instead.
$ErrorActionPreference = 'Continue'

# service name -> build context directory, image tag, needs contract compile
$catalogue = @{
    'authentication' = @{ Directory = 'authentication'; Image = 'iep/authentication'; Compile = $false }
    'employee'       = @{ Directory = 'employee';       Image = 'iep/employee';       Compile = $false }
    'director'       = @{ Directory = 'director';       Image = 'iep/director';       Compile = $true  }
    'public-search'  = @{ Directory = 'public_search';  Image = 'iep/public-search';  Compile = $false }
}


function Invoke-BuilderPatch {
    param([string] $Image, [string] $Directory)

    # BuildKit off, so the local FROM image is taken directly instead of being
    # resolved against the registry. $env: is process-wide, so the previous
    # value is put back - otherwise every later docker command in this window
    # would silently keep using the legacy builder.
    $previous = $env:DOCKER_BUILDKIT
    $env:DOCKER_BUILDKIT = '0'
    try {
        docker build -f (Join-Path $Directory 'Dockerfile.patch') -t $Image $Directory
        return ($LASTEXITCODE -eq 0)
    } finally {
        if ($null -eq $previous) {
            Remove-Item Env:\DOCKER_BUILDKIT -ErrorAction SilentlyContinue
        } else {
            $env:DOCKER_BUILDKIT = $previous
        }
    }
}


function Invoke-CommitPatch {
    param([string] $Image, [string] $Directory, [bool] $Compile)

    # No builder involved: make a container from the image, copy the sources
    # in, and commit it back over the same tag.
    $container = "iep-patch-$(Get-Random)"

    docker create --name $container $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { return $false }

    docker cp "$Directory/." "${container}:/service"
    $copied = ($LASTEXITCODE -eq 0)

    if ($copied) {
        docker commit $container $Image | Out-Null
        $copied = ($LASTEXITCODE -eq 0)
    }
    docker rm -f $container | Out-Null
    if (-not $copied) { return $false }

    if (-not $Compile) { return $true }

    # Recompile Voting.sol with the solc already inside the image. Running it
    # means overriding the entrypoint, and commit would record that override -
    # so read the real entrypoint first and put it back explicitly. The inner
    # quotes are backslash-escaped because PowerShell strips them otherwise,
    # and docker would then read the value as a shell command instead of JSON.
    $entrypoint = docker image inspect $Image --format '{{json .Config.Entrypoint}}'
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($entrypoint)) { return $false }
    $entrypoint = $entrypoint.Trim().Replace('"', '\"')

    $builder = "iep-patch-$(Get-Random)"
    docker run --name $builder --entrypoint python $Image compile_contract.py
    $compiled = ($LASTEXITCODE -eq 0)

    if ($compiled) {
        docker commit --change "ENTRYPOINT $entrypoint" $builder $Image | Out-Null
        $compiled = ($LASTEXITCODE -eq 0)
    }
    docker rm -f $builder | Out-Null

    return $compiled
}


if ($Service -eq 'all') {
    $targets = @('authentication', 'employee', 'director', 'public-search')
} else {
    $targets = @($Service)
}

foreach ($name in $targets) {
    $entry     = $catalogue[$name]
    $directory = Join-Path $PSScriptRoot $entry.Directory
    $image     = $entry.Image + ':latest'

    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan

    docker image inspect $image *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  $image does not exist yet." -ForegroundColor Red
        Write-Host "  A patch layers onto an existing image, so build it once while" -ForegroundColor Red
        Write-Host "  you still have network:  docker compose build $name" -ForegroundColor Red
        exit 1
    }

    $ok = Invoke-BuilderPatch -Image $image -Directory $directory

    if (-not $ok) {
        Write-Host "  legacy builder did not work, falling back to commit" -ForegroundColor Yellow
        $ok = Invoke-CommitPatch -Image $image -Directory $directory -Compile $entry.Compile
    }

    if (-not $ok) {
        Write-Host "  patch FAILED - see the output above." -ForegroundColor Red
        exit 1
    }
    Write-Host "  patched $image" -ForegroundColor Green

    if ($Kubernetes) {
        kubectl rollout restart "deployment/$name"
        kubectl rollout status  "deployment/$name" --timeout=120s
    } else {
        docker compose up -d --force-recreate --no-deps $name
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  restart FAILED - see the output above." -ForegroundColor Red
        exit 1
    }
    Write-Host "  restarted $name" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done. Check it is actually running:" -ForegroundColor Cyan
if ($Kubernetes) {
    Write-Host "  kubectl get pods"
    Write-Host "  kubectl logs -l app=$($targets[0]) --tail=30"
} else {
    Write-Host "  docker compose ps"
    Write-Host "  docker compose logs $($targets[0]) --tail=30"
}
