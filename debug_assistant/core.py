# debug_assistant/core.py
import inspect
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import requests
import docker
from docker.errors import DockerException

class DebuggingAssistant:
    def __init__(self, project_root: str, model_endpoint: str = "http://localhost:11434"):
        self.project_root = Path(project_root)
        self.model_endpoint = model_endpoint
        self.docker_client = docker.from_env()
        self.logger = self.setup_logger()

    def setup_logger(self):
        logger = logging.getLogger("DebugAssistant")
        logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler(self.project_root/'debug.log')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
        return logger

    def analyze_error(self, error: Exception, context: Dict[str, Any]) -> Dict[str, Any]:
        code_snippet = self.get_code_snippet(context['file_path'], context['line_number'])
        prompt = f"""Debug the following Python error:
        Error: {str(error)}
        File: {context['file_path']}
        Line: {context['line_number']}
        Code snippet:
        {code_snippet}

        Suggest specific code changes with explanation. Include necessary logging."""
        
        try:
            response = requests.post(
                f"{self.model_endpoint}/generate",
                json={"prompt": prompt, "model": "deepseek-r1-7b"}
            )
            return response.json()
        except Exception as e:
            self.logger.error(f"Model request failed: {str(e)}")
            return {"solution": "Add logging and check inputs", "code_changes": {}}

    def apply_code_changes(self, changes: Dict[str, Any]):
        for file_path, modifications in changes.items():
            full_path = self.project_root/file_path
            with open(full_path, 'r') as f:
                code = f.readlines()
            
            for line_num, new_code in modifications.items():
                code[line_num-1] = new_code + '\n'
            
            with open(full_path, 'w') as f:
                f.writelines(code)

    def generate_tests(self):
        prompt = """Generate comprehensive pytest tests for the current API endpoints.
        Include test cases for success and failure scenarios."""
        
        response = requests.post(
            f"{self.model_endpoint}/generate",
            json={"prompt": prompt, "model": "deepseek-r1-7b"}
        )
        
        test_file = self.project_root/'tests'/'test_example.py'
        test_file.parent.mkdir(exist_ok=True)
        test_file.write_text(response.json()['code'])

    def run_tests(self) -> bool:
        result = subprocess.run(
            ['pytest', 'tests/test_example.py'],
            cwd=self.project_root,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            self.logger.error(f"Tests failed:\n{result.stderr}")
            return False
        return True

    def start_server(self, use_docker: bool = False):
        if use_docker:
            try:
                self.docker_client.containers.run(
                    "my-fastapi-app",
                    detach=True,
                    ports={'8000': '8000'},
                    volumes={self.project_root: {'bind': '/app', 'mode': 'rw'}}
                )
            except DockerException as e:
                self.logger.error(f"Docker start failed: {str(e)}")
        else:
            subprocess.Popen(
                ['uvicorn', 'main:app', '--reload'],
                cwd=self.project_root
            )

    def get_code_snippet(self, file_path: str, line_num: int, context_lines: int = 5) -> str:
        full_path = self.project_root/file_path
        with open(full_path, 'r') as f:
            lines = f.readlines()
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        return ''.join(lines[start:end])

# Middleware für FastAPI
from fastapi import Request, Response
from fastapi.middleware.base import BaseHTTPMiddleware

class DebugMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, debug_assistant: DebuggingAssistant):
        super().__init__(app)
        self.debug_assistant = debug_assistant

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            frame = inspect.trace()[-1]
            context = {
                'file_path': frame.filename,
                'line_number': frame.lineno,
                'endpoint': request.url.path
            }
            
            analysis = self.debug_assistant.analyze_error(e, context)
            self.debug_assistant.apply_code_changes(analysis['code_changes'])
            
            if analysis.get('additional_logging'):
                self.debug_assistant.logger.info(
                    f"Added logging at {context['file_path']}:{context['line_number']}"
                )
            
            self.debug_assistant.generate_tests()
            if not self.debug_assistant.run_tests():
                self.debug_assistant.start_server()
            
            return Response(
                content="Error processed. Please retry the request.",
                status_code=500
            )