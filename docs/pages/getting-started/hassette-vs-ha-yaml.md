# Hassette vs. Home Assistant YAML Automations

Home Assistant includes a built-in automation system using YAML. Hassette lets you write automations in Python instead. Here's how to decide which is right for you.

## Home Assistant YAML Automations

YAML automations are built into Home Assistant and work great for straightforward automation needs.

**Good for:**

- Simple trigger-action automations (turn on lights when motion detected)
- Quick prototyping and experimentation
- Users who prefer visual editors over code
- No installation required—works out of the box

**Limitations:**

- Complex logic becomes hard to read and maintain in YAML
- Limited code reuse across automations
- Jinja2 templates can be restrictive for advanced logic
- Debugging and testing requires workarounds
- No type safety—errors only appear at runtime

**Best for:** Simple automations you can manage through the UI. If you're happy with YAML automations, stick with them.

## Hassette

Hassette brings Python's power to Home Assistant automations. This unlocks capabilities that are difficult or impossible in YAML.

**Good for:**

- Complex logic with conditionals, loops, and data structures
- Reusable functions and shared code across automations
- Type safety with Python type hints and Pydantic models
- Built-in testing and debugging tools from Python's ecosystem
- Persistent state management without workarounds
- Async/await for efficient concurrent operations

**Trade-offs:**

- Requires Python knowledge (basic understanding is enough to start)
- Additional setup and configuration needed
- Managing Python dependencies for your automations

**Best for:** Automations that have grown too complex for YAML, or when you need features like persistent state, code reuse, or proper testing.

## Making the Decision

**Stick with YAML if:**
- Your automations are simple trigger-action patterns
- You're new to programming and want the easiest path
- The Home Assistant UI works well for your needs

**Consider Hassette if:**
- You're hitting YAML's limitations (complex conditions, state tracking, code reuse)
- You want to test and debug automations like regular code
- You're comfortable with basic Python or willing to learn
- You need your automations to maintain state across runs
