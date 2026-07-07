import asyncio
import sys

print("Platform:", sys.platform)
policy = asyncio.get_event_loop_policy()
print("Current policy:", type(policy))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    print("New policy:", type(asyncio.get_event_loop_policy()))
    loop = asyncio.new_event_loop()
    print("New loop type:", type(loop))
    loop.close()
