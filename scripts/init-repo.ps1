# Inicializa el repositorio y crea la rama prod.
#
# Por que existe este script: la sesion remota puede escribir archivos en la
# carpeta montada pero no borrarlos, y git necesita borrar `.git/index.lock`
# despues de cada operacion que escribe el indice. Quedo un `.git/` a medio
# hacer con un lock atascado. Esto lo limpia y arranca de cero.
#
# Correr desde la raiz del proyecto, en PowerShell:
#
#     .\scripts\init-repo.ps1

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".gitignore")) {
    Write-Error "Corra este script desde la raiz del proyecto (donde esta .gitignore)."
}

# 1. Limpiar el repo a medio inicializar que dejo la sesion remota.
if (Test-Path ".git") {
    Write-Host "Eliminando el .git incompleto..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".git"
}

# 2. Repo limpio, rama main.
git init -b main
git config user.name  "Juan M"
git config user.email "juanlmacad@gmail.com"

# 3. Verificar que lo sensible no entre. Si algo de esto aparece, parar.
git add -A
$peligro = git status --short | Select-String -Pattern '\.env|secretos/|firma\.sk'
if ($peligro) {
    Write-Host ""
    Write-Host "ALTO: hay archivos sensibles en el indice:" -ForegroundColor Red
    $peligro
    Write-Host "Revise el .gitignore antes de commitear." -ForegroundColor Red
    git reset
    exit 1
}

Write-Host ""
Write-Host "Archivos que entran al primer commit:" -ForegroundColor Cyan
git status --short

# 4. Primer commit en main: el estado de sandbox, que ya funciona.
git commit -q -m "Sandbox verificado de punta a punta

Boveda de mandatos firmados ed25519 sobre fuentes de pago de Wompi.
Banco de pruebas de la pasarela e informe de viabilidad de rieles
colombianos. Todo contra sandbox: ninguna llave de produccion."

# 5. La rama de produccion sale de ahi.
git branch prod
git checkout prod

Write-Host ""
Write-Host "Listo." -ForegroundColor Green
Write-Host "  main  sandbox, intacto"
Write-Host "  prod  <- esta aqui. Dinero real."
Write-Host ""
git log --oneline
git branch
