def frontend():
    import subprocess
    subprocess.run(
        ["npm", "run", "dev"],
        cwd="frontend",
        check=True
    )

def backend():
    import uvicorn
    uvicorn.run("backend.main:app", reload=True)

def tests():
    import pytest
    raise SystemExit(pytest.main())