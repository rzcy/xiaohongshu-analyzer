"""HTML报告导出工具 - 支持将HTML转为PNG图片"""
import tempfile
import os


def html_to_screenshot(html_string: str, width: int = 1200) -> bytes:
    """
    将HTML字符串转换为PNG截图
    使用 Selenium + Chromium headless 方案

    返回: PNG二进制数据，失败则抛出异常
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument(f"--window-size={width},900")

    # 尝试多种方式找到 Chrome/Chromium（macOS + Linux）
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
        "/Applications/Chromium.app/Contents/MacOS/Chromium",  # macOS Chromium
        "/usr/bin/chromium-browser",  # Linux
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
    ]

    for path in chrome_paths:
        if os.path.exists(path):
            chrome_options.binary_location = path
            break

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
    except Exception:
        service = Service()  # 尝试系统默认

    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        # 写入临时文件（避免 data URI 长度限制）
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_string)
            tmp_path = f.name

        driver.get(f"file://{tmp_path}")

        import time
        time.sleep(1)  # 等待渲染

        # 获取完整页面高度
        body_height = driver.execute_script("return document.body.scrollHeight")
        driver.set_window_size(width, body_height + 100)
        time.sleep(0.5)

        screenshot_bytes = driver.get_screenshot_as_png()
        return screenshot_bytes
    finally:
        driver.quit()
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
