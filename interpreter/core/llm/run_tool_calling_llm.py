from builtins import print
import os
import re

from .utils.merge_deltas import merge_deltas
from .utils.parse_partial_json import parse_partial_json

# # Chat Completions-style tool schema
# tool_schema = {
#     "type": "function",
#     "function": {
#         "name": "execute",
#         "description": "Executes code on the user's machine **in the users local environment** and returns the output",
#         "parameters": {
#             "type": "object",
#             "properties": {
#                 "language": {
#                     "type": "string",
#                     "description": "The programming language (required parameter to the `execute` function)",
#                     "enum": [
#                         # This will be filled dynamically with the languages OI has access to.
#                     ],
#                 },
#                 "code": {
#                     "type": "string",
#                     "description": "The code to execute (required)",
#                 },
#             },
#             "required": ["language", "code"],
#         },
#     },
# }

# Responses-compliant tool schema (top-level name)
tool_schema = {
    "type": "function",
    "name": "execute",
    "description": "Executes code on the user's machine **in the users local environment** and returns the output",
    "parameters": {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "description": "The programming language (required parameter to the `execute` function)",
                "enum": [],  # filled dynamically below
            },
            "code": {
                "type": "string",
                "description": "The code to execute (required)",
            },
        },
        "required": ["language", "code"],
    },
}

def process_messages(messages):
    processed_messages = []
    last_tool_id = 0

    i = 0
    while i < len(messages):
        message = messages[i]

        if message.get("function_call"):
            last_tool_id += 1
            tool_id = f"toolu_{last_tool_id}"

            # Convert function_call to tool_calls
            function = message.pop("function_call")
            message["tool_calls"] = [
                {"id": tool_id, "type": "function", "function": function}
            ]
            processed_messages.append(message)

            # Process the next message if it's a function response
            if i + 1 < len(messages) and messages[i + 1].get("role") == "function":
                next_message = messages[i + 1].copy()
                next_message["role"] = "tool"
                next_message["tool_call_id"] = tool_id
                processed_messages.append(next_message)
                i += 1  # Skip the next message as we've already processed it
            else:
                # Add an empty tool response if there isn't one
                processed_messages.append(
                    {"role": "tool", "tool_call_id": tool_id, "content": ""}
                )

        elif message.get("role") == "function":
            # This handles orphaned function responses
            last_tool_id += 1
            tool_id = f"toolu_{last_tool_id}"

            # Add a tool call before this orphaned tool response
            processed_messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": "execute",
                                "arguments": "# Automated tool call to fetch more output, triggered by the user.",
                            },
                        }
                    ],
                }
            )

            # Process the function response
            message["role"] = "tool"
            message["tool_call_id"] = tool_id
            processed_messages.append(message)

        else:
            # For non-tool-related messages, just add them as is
            processed_messages.append(message)

        i += 1

    return processed_messages


def run_tool_calling_llm(llm, request_params):
    
    print("[run_tool_calling_llm] keys in request_params:", list(request_params.keys()), flush=True)

    ## Setup
    
    # Add languages OI has access to

    # # Chat Completions ONLY
    # tool_schema["function"]["parameters"]["properties"]["language"]["enum"] = [
    #     i.name.lower() for i in llm.interpreter.computer.terminal.languages
    # ]

    # Responses-style Completions
    tool_schema["parameters"]["properties"]["language"]["enum"] = [
        i.name.lower() for i in llm.interpreter.computer.terminal.languages
    ]

    # Only include tools when the model supports functions
    if llm.supports_functions:
        request_params["tools"] = [tool_schema]
        request_params.setdefault("tool_choice", "auto")
    else:
        request_params.pop("tools", None)
        request_params.pop("tool_choice", None)

    # request_params["messages"] = process_messages(request_params["messages"]) # Chat Completions ONLY
    
    # Accept both shapes; prefer Responses "input"
    msgs = None
    if "input" in request_params:
        msgs = request_params["input"]
    elif "messages" in request_params:
        # Legacy fallback: allow old callers to still work
        msgs = request_params["messages"]
    else:
        msgs = []

    # Run the same tool-call normalization over whichever we got
    msgs = process_messages(msgs)

    # Keep it in Responses shape for litellm.responses()
    request_params["input"] = msgs

    # IMPORTANT: do not keep/restore a "messages" key when using Responses
    if "messages" in request_params:
        del request_params["messages"]

    # # This makes any role: tool have the ID of the last tool call
    # last_tool_id = 0
    # for i, message in enumerate(request_params["messages"]):
    #     if "function_call" in message:
    #         last_tool_id += 1
    #         function = message.pop("function_call")
    #         message["tool_calls"] = [
    #             {
    #                 "id": "toolu_" + str(last_tool_id),
    #                 "type": "function",
    #                 "function": function,
    #             }
    #         ]
    #     if message["role"] == "function":
    #         if i != 0 and request_params["messages"][i - 1]["role"] == "tool":
    #             request_params["messages"][i]["content"] += message["content"]
    #             message = None
    #         else:
    #             message["role"] = "tool"
    #             message["tool_call_id"] = "toolu_" + str(last_tool_id)
    # request_params["messages"] = [m for m in request_params["messages"] if m != None]

    # This adds an empty tool response for any tool call without a tool response
    # new_messages = []
    # for i, message in enumerate(request_params["messages"]):
    #     new_messages.append(message)
    #     if "tool_calls" in message:
    #         tool_call_id = message["tool_calls"][0]["id"]
    #         if not any(
    #             m
    #             for m in request_params["messages"]
    #             if m.get("role") == "tool" and m.get("tool_call_id") == tool_call_id
    #         ):
    #             new_messages.append(
    #                 {"role": "tool", "tool_call_id": tool_call_id, "content": ""}
    #             )
    # request_params["messages"] = new_messages

    # messages = request_params["messages"]
    # for i in range(len(messages)):
    #     if messages[i]["role"] == "user" and isinstance(messages[i]["content"], list):
    #         # Found an image from the user
    #         image_message = messages[i]
    #         j = i + 1
    #         while j < len(messages) and messages[j]["role"] == "tool":
    #             # Move the image down until it's after all the role: tools
    #             j += 1
    #         messages.insert(j, image_message)
    #         del messages[i]
    # request_params["messages"] = messages

    # Add OpenAI's recommended function message
    # request_params["messages"][0][
    #     "content"
    # ] += "\nUse ONLY the function you have been provided with — 'execute(language, code)'."

    ## Convert output to LMC format

    accumulated_deltas = {}
    language = None
    code = ""
    function_call_detected = False
    accumulated_review = ""
    review_category = None
    buffer = ""

    for chunk in llm.completions(**request_params):

        # --- NEW: handle Responses tool events directly ---
        if "tool_event" in chunk:
            ev = chunk["tool_event"]
            # robust access for both objects and dicts
            ev_type = getattr(ev, "type", None) or (ev.get("type") if isinstance(ev, dict) else None)

            if not ev_type:
                continue

            # Start of a tool call -> capture function name
            if ev_type.endswith(".created"):
                item = getattr(ev, "item", None) or (ev.get("item") if isinstance(ev, dict) else None)
                fn   = getattr(item, "function", None) or (item.get("function") if isinstance(item, dict) else None)
                name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
                accumulated_deltas.setdefault("function_call", {"name": None, "arguments": ""})
                if name:
                    accumulated_deltas["function_call"]["name"] = name
                function_call_detected = True
                continue

            # Streaming arguments -> append to our accumulator
            if ev_type.endswith(".delta"):
                d = getattr(ev, "delta", None) or (ev.get("delta") if isinstance(ev, dict) else None)
                # In Responses, the delta may contain just the new substring for `arguments`
                args_delta = None
                if isinstance(d, dict):
                    args_delta = d.get("arguments")
                else:
                    args_delta = getattr(d, "arguments", None)

                if args_delta:
                    accumulated_deltas.setdefault("function_call", {"name": None, "arguments": ""})
                    accumulated_deltas["function_call"]["arguments"] += args_delta

                    # NEW: parse accumulated args and stream code deltas immediately (Responses path)
                    args_text = accumulated_deltas["function_call"]["arguments"]
                    args_obj = parse_partial_json(args_text) or {}

                    # set language as soon as it's fully present
                    if language is None and args_obj.get("language"):
                        language = args_obj["language"]

                    # stream incremental code pieces to the executor
                    if "code" in args_obj:
                        new_code = args_obj.get("code") or ""
                        piece = new_code[len(code):]
                        code = new_code
                        if piece:
                            yield {
                                "type": "code",
                                "format": (language or "python"),
                                "content": piece,
                            }
                continue

            # Completed -> nothing extra to do here
            if ev_type.endswith(".completed"):
                continue
        # --- END NEW ---

        if "choices" not in chunk or not chunk["choices"]:
            # This happens sometimes
            continue

        choice0 = chunk["choices"][0]
        delta = choice0.get("delta")

        # Finish-only chunk from the adapter (no delta present)
        if delta is None:
            finish = choice0.get("finish_reason")
            if finish == "stop":
                break
            if finish == "error":
                raise RuntimeError("Model returned an error finish.")
            # Unknown non-delta chunk; skip
            continue

        # # Convert tool call into function call, which we have great parsing logic for below
        # if "tool_calls" in delta and delta["tool_calls"]:
        #     function_call_detected = True
            # # import pdb; pdb.set_trace()
            # if len(delta["tool_calls"]) > 0 and delta["tool_calls"][0].function:
            #     delta = {
            #         # "id": delta["tool_calls"][0],
            #         "function_call": {
            #             "name": delta["tool_calls"][0].function.name,
            #             "arguments": delta["tool_calls"][0].function.arguments,
            #         }
            #     }

        # Convert Chat Completions-style tool_calls → function_call
        if "tool_calls" in delta and delta["tool_calls"]:
            function_call_detected = True

            tc0 = delta["tool_calls"][0]
            fn = getattr(tc0, "function", None) or (tc0.get("function") if isinstance(tc0, dict) else None)

            if fn:
                name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
                args = getattr(fn, "arguments", None) or (fn.get("arguments") if isinstance(fn, dict) else "")

                # Ensure arguments is a string for your merge_deltas + incremental parsing
                if not isinstance(args, str):
                    try:
                        import json
                        args = json.dumps(args, ensure_ascii=False)
                    except Exception:
                        args = str(args)

                # Merge instead of replacing to avoid losing other delta keys
                new_delta = {k: v for k, v in delta.items() if k != "tool_calls"}
                new_delta["function_call"] = {"name": name, "arguments": args}
                delta = new_delta

        # Accumulate deltas
        accumulated_deltas = merge_deltas(accumulated_deltas, delta)

        if "content" in delta and delta["content"]:
            if function_call_detected:
                # More content after a code block? This is a code review by a judge layer.

                # print("Code safety review:", delta["content"])

                if review_category == None:
                    accumulated_review += delta["content"]

                    if "<unsafe>" in accumulated_review:
                        review_category = "unsafe"
                    if "<warning>" in accumulated_review:
                        review_category = "warning"
                    if "<safe>" in accumulated_review:
                        review_category = "safe"

                if review_category != None:
                    for tag in [
                        "<safe>",
                        "</safe>",
                        "<warning>",
                        "</warning>",
                        "<unsafe>",
                        "</unsafe>",
                    ]:
                        delta["content"] = delta["content"].replace(tag, "")

                    if re.search("</.*>$", accumulated_review):
                        buffer += delta["content"]
                        continue
                    elif buffer:
                        yield {
                            "type": "review",
                            "format": review_category,
                            "content": buffer + delta["content"],
                        }
                        buffer = ""
                    else:
                        yield {
                            "type": "review",
                            "format": review_category,
                            "content": delta["content"],
                        }
                        buffer = ""

            else:
                yield {"type": "message", "content": delta["content"]}

        if (
            accumulated_deltas.get("function_call")
            and "name" in accumulated_deltas["function_call"]
            and (
                accumulated_deltas["function_call"]["name"] == "python"
                or accumulated_deltas["function_call"]["name"] == "functions"
                or accumulated_deltas["function_call"]["name"] == "execute"
            )
        ):
            if language is None:
                language = "python"

            # Pull the code string straight out of the "arguments" string
            code_delta = accumulated_deltas["function_call"]["arguments"][len(code) :]
            # Update the code
            code = accumulated_deltas["function_call"]["arguments"]
            # Yield the delta
            if code_delta:
                yield {
                    "type": "code",
                    "format": language,
                    "content": code_delta,
                }

        if (
            accumulated_deltas.get("function_call")
            and "arguments" in accumulated_deltas["function_call"]
            and accumulated_deltas["function_call"]["arguments"]
        ):
            if "arguments" in accumulated_deltas["function_call"]:
                arguments = accumulated_deltas["function_call"]["arguments"]
                arguments = parse_partial_json(arguments)

                if arguments:
                    if (
                        language is None
                        and "language" in arguments
                        and "code"
                        in arguments  # <- This ensures we're *finished* typing language, as opposed to partially done
                        and arguments["language"]
                    ):
                        language = arguments["language"]

                    if language is not None and "code" in arguments:
                        # Calculate the delta (new characters only)
                        code_delta = arguments["code"][len(code) :]
                        # Update the code
                        code = arguments["code"]
                        # Yield the delta
                        if code_delta:
                            yield {
                                "type": "code",
                                "format": language,
                                "content": code_delta,
                            }
                else:
                    if llm.interpreter.verbose:
                        print("Arguments not a dict.")

    if os.getenv("INTERPRETER_REQUIRE_AUTHENTICATION", "False").lower() == "true":
        print("function_call_detected", function_call_detected)
        print("accumulated_review", accumulated_review)
        if function_call_detected and not accumulated_review:
            print("WTF!!!!!!!!!")
            # import pdb
            # pdb.set_trace()
            raise Exception("Judge layer required but did not run.")
