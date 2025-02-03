from typing import Annotated, Any
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

def create_browser() -> Browser:
    return Browser(
        config=BrowserConfig(
            headless=False,
            chrome_instance_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
    )

async def web_search(input: Annotated[str, "what to search for"]) -> Any:
    """Search the web for the input."""
    browser = create_browser()
    model = ChatOpenAI(model='gpt-4o')
    agent = Agent(
        task=input,
        llm=model,
        controller=Controller(),
        browser=browser,
    )
    result = await agent.run()
    return result