@echo off
setlocal
cd /d "%~dp0"
if not defined TWS_API_INCLUDE set "TWS_API_INCLUDE=C:\TWS API\source\CppClient\client"
if not defined LIBBID_PATH set "LIBBID_PATH=C:\Users\yahav\Downloads\IntelRDFPMathLib20U3\LIBRARY\libbid.lib"
if not defined VCVARS64_PATH set "VCVARS64_PATH=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined PYTHON_EXE set "PYTHON_EXE=python"
if not exist "%TWS_API_INCLUDE%\bar.h" (echo Missing TWS API headers & exit /b 1)
if not exist "%LIBBID_PATH%" (echo Missing Intel decimal library & exit /b 1)
call "%VCVARS64_PATH%" >nul
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" generate_adapter.py
if errorlevel 1 exit /b 1
cl /nologo /std:c++latest /EHsc /O2 /W3 /D_CRT_SECURE_NO_WARNINGS /I"%TWS_API_INCLUDE%" /FI"%~dp0build\prelude.h" /c "..\traderBot\DataFetcher.cpp" /Fo"build\DataFetcher.obj" /Fd"build\compiler.pdb"
if errorlevel 1 exit /b 1
cl /nologo /std:c++latest /EHsc /O2 /W3 /D_CRT_SECURE_NO_WARNINGS /I"%TWS_API_INCLUDE%" /FI"%~dp0build\prelude.h" /c "%TWS_API_INCLUDE%\Decimal.cpp" /Fo"build\Decimal.obj" /Fd"build\compiler.pdb"
if errorlevel 1 exit /b 1
cl /nologo /std:c++latest /EHsc /O2 /W3 /D_CRT_SECURE_NO_WARNINGS /I"%TWS_API_INCLUDE%" /FI"%~dp0build\prelude.h" /c "build\strategy_adapter.generated.cpp" /Fo"build\strategy_adapter.obj" /Fd"build\compiler.pdb"
if errorlevel 1 exit /b 1
cl /nologo /std:c++latest /EHsc /O2 /W3 /D_CRT_SECURE_NO_WARNINGS /I"%TWS_API_INCLUDE%" /FI"%~dp0build\prelude.h" "adapter_tests.cpp" /Fo"build\adapter_tests.obj" /Fd"build\compiler.pdb" "build\DataFetcher.obj" "build\Decimal.obj" "build\strategy_adapter.obj" "%LIBBID_PATH%" /Fe"build\adapter_tests.exe" /link /PDB:"build\adapter_tests.pdb"
if errorlevel 1 exit /b 1
if /i "%~1"=="--adapter-only" exit /b 0
cl /nologo /std:c++latest /EHsc /O2 /W3 /D_CRT_SECURE_NO_WARNINGS /I"%TWS_API_INCLUDE%" /FI"%~dp0build\prelude.h" "engine.cpp" /Fo"build\engine.obj" /Fd"build\compiler.pdb" "build\DataFetcher.obj" "build\Decimal.obj" "build\strategy_adapter.obj" "%LIBBID_PATH%" /Fe"build\replay.exe" /link /PDB:"build\replay.pdb"
exit /b %errorlevel%

