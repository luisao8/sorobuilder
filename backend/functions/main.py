# Backend code with fixes applied

from firebase_functions import https_fn
from firebase_admin import initialize_app
import functions_framework
from flask import jsonify
from openai import OpenAI, AssistantEventHandler
from typing_extensions import override
import os
import pusher
import logging
from threading import Thread
import json
import re
import firebase_admin
from firebase_admin import initialize_app, credentials, firestore
import datetime
import uuid
from flask import make_response


OPEN_AI_KEY=os.getenv("OPEN_AI_KEY")
PUSHER_APP_ID=os.getenv("PUSHER_APP_ID")
PUSHER_KEY=os.getenv("PUSHER_KEY")
PUSHER_SECRET=os.getenv("PUSHER_SECRET")
ASSISTANT_QUESTIONER_ID=os.getenv("ASSISTANT_QUESTIONER_ID")
ASSISTANT_DESIGNER_ID=os.getenv("ASSISTANT_DESIGNER_ID")
ASSISTANT_BUILDER_ID=os.getenv("ASSISTANT_BUILDER_ID")
ASSISTANT_TEST_BUILDER_ID=os.getenv("ASSISTANT_TEST_BUILDER_ID")
ASSISTANT_DOCUMENTATION_ID=os.getenv("ASSISTANT_DOCUMENTATION_ID")

# Initialize OpenAI client
client = OpenAI(api_key=OPEN_AI_KEY)
cred = credentials.Certificate("key.json")
firebase_admin.initialize_app(cred)
db = firestore.client()


# Initialize Pusher client
pusher_client = pusher.Pusher(
  app_id=PUSHER_APP_ID,
  key=PUSHER_KEY,
  secret=PUSHER_SECRET,
  cluster='eu',
  ssl=True
)

# Define the generate_contract function schema for function calling
generate_contract_function = {
    "name": "generate_contract",
    "description": "Initiate the contract generation process when all information has been gathered.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    "strict": True
}

# Define the EventHandler class to handle streaming from assistants
class EventHandler(AssistantEventHandler):
    def __init__(self, pusher_client, thread_id, channel_id, event_type, is_code_generation=False):
        super().__init__()
        self.pusher_client = pusher_client
        self.thread_id = thread_id
        self.channel_id = channel_id
        self.event_type = event_type
        self.full_response = ""
        self.message_in_progress = False
        self.generate_contract_called = False
        self.is_code_generation = is_code_generation
        self.buffer = ""
        self.state = 'normal'

    @override
    def on_text_created(self, text):
        self.message_in_progress = True
        self.full_response = ""
        logging.info(f"Starting new message in channel {self.channel_id}")
        print(f"\n--- Starting new {self.event_type} ---")
        self.pusher_client.trigger(self.channel_id, self.event_type, {
            'message_start': True,
            'thread_id': self.thread_id,
        })

    @override
    def on_text_delta(self, delta, snapshot):
        if self.message_in_progress:
            self.full_response += delta.value
            if self.is_code_generation:
                self.buffer += delta.value

                while True:
                    if self.state == 'normal':
                        # Look for the start of a code block
                        start_match = re.search(r'```', self.buffer)
                        if start_match:
                            # Transition to awaiting_language state
                            self.state = 'awaiting_language'
                            # Remove everything before and including the '```'
                            self.buffer = self.buffer[start_match.end():]
                        else:
                            # No code block start found; exit the loop
                            break

                    elif self.state == 'awaiting_language':
                        # Check if there's a newline indicating the end of the language identifier
                        newline_index = self.buffer.find('\n')
                        if newline_index != -1:
                            # Potentially have a language identifier; skip it
                            # Remove the language identifier and the newline
                            self.buffer = self.buffer[newline_index+1:]
                            # Transition to in_code_block state
                            self.state = 'in_code_block'
                        else:
                            # Wait for more data to determine if there's a language identifier
                            break

                    elif self.state == 'in_code_block':
                        # Look for the end of the code block
                        end_match = re.search(r'```', self.buffer)
                        if end_match:
                            # Found the end of the code block
                            code_content = self.buffer[:end_match.start()]
                            if code_content:
                                self.pusher_client.trigger(self.channel_id, 'code-chunk', {
                                    'content': code_content,
                                    'filePath': self.current_file_path,
                                    'thread_id': self.thread_id,
                                })
                            # Remove the processed code and the closing delimiter
                            self.buffer = self.buffer[end_match.end():]
                            # Transition back to normal state
                            self.state = 'normal'
                        elif self.buffer.endswith('```'):
                            # Handle case where '```' is at the end of the buffer
                            code_content = self.buffer[:-3]
                            if code_content:
                                self.pusher_client.trigger(self.channel_id, 'code-chunk', {
                                    'content': code_content,
                                    'filePath': self.current_file_path,
                                    'thread_id': self.thread_id,
                                })
                            # Remove '```' from buffer
                            self.buffer = ''
                            self.state = 'normal'
                        else:
                            # No end delimiter found yet; send the buffer as code content
                            if self.buffer:
                                # Before sending, ensure we don't include partial '```' at the end
                                # Check for partial delimiter at the end
                                partial_delimiter_match = re.search(r'`+$', self.buffer)
                                if partial_delimiter_match:
                                    # Exclude the partial delimiter from code content
                                    code_content = self.buffer[:partial_delimiter_match.start()]
                                    # Keep the partial delimiter in the buffer
                                    self.buffer = self.buffer[partial_delimiter_match.start():]
                                else:
                                    code_content = self.buffer
                                    self.buffer = ''

                                if code_content:
                                    self.pusher_client.trigger(self.channel_id, 'code-chunk', {
                                        'content': code_content,
                                        'filePath': self.current_file_path,
                                        'thread_id': self.thread_id,
                                    })
                            # Break to wait for more data
                            break
            else:
                # Handle non-code messages
                self.pusher_client.trigger(self.channel_id, self.event_type, {
                    'message': delta.value,
                    'thread_id': self.thread_id,
                    'is_complete': False
                })

    @override
    def on_text_done(self, text):
        self.message_in_progress = False
        print(f"\n--- End of {self.event_type} ---\n")
        logging.info(f"Message completed. Sending full response to channel {self.channel_id}")
        # Send the complete message
        self.pusher_client.trigger(self.channel_id, self.event_type, {
            'message': self.full_response,  # Send the accumulated response
            'thread_id': self.thread_id,
            'is_complete': True
        })

    @override
    def on_tool_call_created(self, tool_call):
        logging.info(f"Tool call created: {tool_call.type}")
        if tool_call.type == 'function':
            if hasattr(tool_call, 'function') and tool_call.function.name == 'generate_contract':
                self.generate_contract_called = True
                logging.info("Generate contract function called.")
        elif tool_call.type == 'file_search':
            # Handle file search tool call if needed
            pass
        # Add more conditions for other tool call types as necessary

    @override
    def on_run_completed(self, run):
        logging.info(f"Run completed for thread {self.thread_id}")
        self.run_completed = True
        self.pusher_client.trigger(self.channel_id, self.event_type, {
            'run_completed': True,
            'thread_id': self.thread_id,
        })

def add_message(thread_id, content, role):
    # Add user message to the thread
    client.beta.threads.messages.create(
            thread_id=thread_id,
            role=role,
            content=content
        )   
    return

# Main chat handler function
@https_fn.on_request()
def chat_handler(req: https_fn.Request) -> https_fn.Response:
    if req.method == 'OPTIONS':
        # Respond to preflight request
        response = jsonify({'message': 'OK'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        return response

    try:
        print("Starting chat_handler function")
        data = req.get_json()
        user_input = data.get('input')
        thread_id = data.get('thread_id')
        print(f"Thread ID: {thread_id}")
        channel_id = data.get('channel_id')

        print(f"Received request with input: {user_input}, thread_id: {thread_id}, channel_id: {channel_id}")
        logging.info(f"Received request with input: {user_input}, thread_id: {thread_id}, channel_id: {channel_id}")

        if not thread_id:
            print("Creating new thread")
            thread = client.beta.threads.create()
            thread_id = thread.id
            print(f"Created new thread with id: {thread_id}")
            logging.info(f"Created new thread with id: {thread_id}")
        else:
            print(f"Retrieving existing thread with id: {thread_id}")
            thread = client.beta.threads.retrieve(thread_id)
            print(f"Retrieved existing thread with id: {thread_id}")
            logging.info(f"Retrieved existing thread with id: {thread_id}")

        add_message(thread_id, user_input, "user")
        logging.info("Added user message to thread")

        

        print("Creating EventHandler")
        event_handler = EventHandler(pusher_client, thread_id, channel_id, "chat-response")
        
        with client.beta.threads.runs.stream(
            thread_id=thread_id,
            assistant_id=ASSISTANT_QUESTIONER_ID,
            event_handler=event_handler,
            tools=[{
                "type": "function",
                "function": generate_contract_function
            }]
        ) as stream:
            print("Processing stream events")
            for event in stream:
                print(f"Received event: {event.event}")
                logging.info(f"Received event: {event.event}")

                if event.event == "thread.run.requires_action":
                    print("Run requires action")
                    required_action = event.data.required_action
                    if required_action.type == 'submit_tool_outputs':
                        tool_outputs = []
                        for tool_call in required_action.submit_tool_outputs.tool_calls:
                            if tool_call.type == 'function' and tool_call.function.name == 'generate_contract':
                                # Execute the function
                                print("hi")
                                client.beta.threads.runs.cancel(
                                    thread_id=thread_id,
                                    run_id=event.data.id
                                )
                                            # Since the function has no outputs, output is empty
                                tool_outputs.append({
                                    'tool_call_id': tool_call.id,
                                    'output': "Contract generation started. Tell the user to wait a little while the contract is being generated."
                                })
                        
                        # # Submit the tool outputs
                        # print("Submitting tool outputs")
                        # client.beta.threads.runs.submit_tool_outputs(
                        #     thread_id=thread_id,
                        #     run_id=event.data.id,
                        #     tool_outputs=tool_outputs
                        # )
                elif event.event == "thread.run.completed":
                    
                    print("Run completed")
                    # We can proceed
                    
                # Process other events as needed
        if event_handler.generate_contract_called:
            print("Generating contract")
            generate_contract(thread_id, channel_id, user_input)

        print("Stream processing completed")
        response = make_response(jsonify({'message': 'Processing request', 'thread_id': thread_id}))
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    except Exception as e:
        print(f"Error in chat_handler: {str(e)}")
        logging.error(f"Error processing request: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Function to generate the contract
def generate_contract(thread_id, channel_id, user_input):
    logging.info("Generating contract...")
    print("\n=== Starting Contract Generation ===\n")
    
    generated_files = {}
    
    try:
        print("--- Designer Assistant Output ---")
        
        # Use existing chat thread for designer
        event_handler = EventHandler(pusher_client, thread_id, channel_id, "chat-response")
        try:
            with client.beta.threads.runs.stream(
                thread_id=thread_id,  # Using existing chat thread
                assistant_id=ASSISTANT_DESIGNER_ID,
                event_handler=event_handler
            ) as stream:
                stream.until_done()

            # Get designer's output
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            designer_output = messages.data[0].content[0].text.value

            if designer_output.strip():
                # Process the designer's output
                project_name, file_list = extract_file_names(designer_output)

                print(f"\nProject name: {project_name}")
                print(f"Files to be generated: {file_list}\n")

                # Send file structure to front-end
                file_structure = build_file_structure(file_list, project_name)
                pusher_client.trigger(channel_id, 'initial-structure', {
                    'structure': file_structure
                })
                
                # Create single new thread for all builders
                building_thread = client.beta.threads.create()
                building_thread_id = building_thread.id
                
                # Add designer's output to building thread
                add_message(building_thread_id, designer_output, "user")
                
                # Build each file using the same building thread
                for file_info in file_list:
                    print(f"\n--- Building file: {file_info} ---")
                    add_message(building_thread_id, f"Generate the code for {file_info}", "user")
                    code_output = build_file(building_thread_id, channel_id, file_info)
                    generated_files[file_info] = code_output
                    print(f"--- Finished building file: {file_info} ---\n")
                
                # Save contract data and send notifications
                contract_id = save_contract_data(project_name, generated_files, user_input)
                
                pusher_client.trigger(channel_id, 'contract-saved', {
                    'contract_id': contract_id,
                    'project_name': project_name
                })
                
                feedback_message = (
                    "We would greatly appreciate feedback on the product to keep improving. "
                    "Please respond to this survey once you've reviewed the generation of the contract. "
                    "It will be an amazing push of help this project. Take into account this is the first prototype "
                    "and that vast improvements are still possible: "
                    "[Feedback Form](https://forms.gle/ZX6bGYcS2hxPaw5Z6)"
                )
                
                pusher_client.trigger(channel_id, 'chat-response', {
                    'message': feedback_message,
                    'thread_id': thread_id,
                    'is_complete': True
                })
            else:
                logging.error("Designer output was empty")
                raise ValueError("Designer output was empty")
                
        except Exception as e:
            logging.error(f"Error in contract generation: {str(e)}")
            pusher_client.trigger(channel_id, 'error', {
                'message': f"Error generating contract: {str(e)}"
            })
    except Exception as e:
        # Update analytics for failed generations
        analytics_ref = db.collection('analytics').document('contract_generation')
        analytics_ref.set({
            'failed_generations': firestore.Increment(1),
            'last_error': str(e),
            'last_error_timestamp': datetime.datetime.now()
        }, merge=True)
        
        logging.error(f"Error in contract generation: {str(e)}")
        pusher_client.trigger(channel_id, 'error', {
            'message': f"Error generating contract: {str(e)}"
        })

# Function to extract file names using structured outputs
def extract_file_names(designer_output):
    logging.info("Extracting file names and project name from designer output...")
    
    extract_files_function = {
        "name": "extract_file_names",
        "description": "Extracts the project name and list of contract and testfiles from the designer's output.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "The name of the smart contract (e.g., 'liquidity_pool')"
                },
                "src_folder_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file names with proper paths in the order they appear in the design document design"
                },
                "test_folder_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file names with proper paths in the order they appear in the design document design"
                }
            },
            "required": ["project_name", "src_folder_files", "test_folder_files"]
        }
    }

    completion = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {
                "role": "system", 
                "content": """Your task is to extract information from a soroban smart contract design document. You must extract:
                 - The project name.
                 - The list of files in the src folder.
                 - The list of files in the tests folder.
                 
DO NOT include:
- Cargo.toml
- Documentation files (README.md, etc.)
- Any non-Rust files

The project name should be the main contract/project name. For all src files, prefix them with 'src/' if they don't already have it. For all tests prefix them with test/ 

Example output structure:
{
    "project_name": "liquidity_pool",
    "src_folder_files": [
        "src/lib.rs",
        "src/pool.rs",
        "src/token.rs"
    ],
    "test_folder_files": [
        "test/liquidity_pool_test.rs"
    ]
}
Remember: The sequence of files in the output MUST match their appearance order in the design document."""
            },
            {"role": "assistant", "content": designer_output}
        ],
        functions=[extract_files_function],
        function_call={"name": "extract_file_names"}
    )
    
    arguments = completion.choices[0].message.function_call.arguments
    json_dict = json.loads(arguments)
    project_name = json_dict.get("project_name")
    files_list = json_dict.get("src_folder_files", [])
    test_files = json_dict.get("test_folder_files", [])
    
    # Create ordered file structure
    ordered_files = []
    
    # 1. First add all .rs files that aren't tests
    for file in files_list:
        if file.endswith('.rs') and not file.endswith('_test.rs'):
            if not file.startswith('src/'):
                file = f"src/{file}"
            ordered_files.append(file)

    for file in test_files:
        if file.endswith('.rs'):
            if not file.startswith('test/'):
                file = f"test/{file}"
            ordered_files.append(file)

    # 3. Add cargo file
    ordered_files.append("Cargo.toml")

    ordered_files.append("README.md")
    

    return project_name, ordered_files

def build_file_structure(files_list, project_name):
    logging.info("Building file structure...")
    root = [{
        "name": project_name,
        "type": "folder",
        "path": project_name,
        "children": []
    }]
    
    current_level = root[0]["children"]
    
    # Sort files to ensure root files come first
    sorted_files = sorted(files_list, key=lambda x: (x.startswith('src/'), x))
    
    for file_path in sorted_files:
        parts = file_path.split('/')
        level = current_level
        
        # Process each part of the path
        for i, part in enumerate(parts):
            is_file = (i == len(parts) - 1)
            existing = next((item for item in level if item["name"] == part), None)
            
            if is_file:
                if not existing:
                    level.append({
                        "name": part,
                        "type": "file",
                        "path": file_path,  # Use the direct file_path without project name
                        "content": ""
                    })
            else:
                if not existing:
                    new_folder = {
                        "name": part,
                        "type": "folder",
                        "path": '/'.join(parts[:i+1]),  # Path without project name
                        "children": []
                    }
                    level.append(new_folder)
                    level = new_folder["children"]
                else:
                    level = existing["children"]
    
    return root

# Function to build each file using the Builder Assistant
def build_file(building_thread_id, channel_id, file_path):
    logging.info(f"Building file {file_path}...")
    
    # Select appropriate assistant and context based on file type
    if file_path.endswith('_test.rs'):
        assistant_id = ASSISTANT_TEST_BUILDER_ID
        context_message = "[Context for test generation] You have access to all the main Rust source files that have already been generated. Use this context to create appropriate tests."
    elif file_path.endswith('.md'):
        assistant_id = ASSISTANT_DOCUMENTATION_ID
        context_message = "[Context for documentation generation] You have access to all source code, tests, and cargo files. Use this context to create comprehensive documentation."
    else:
        assistant_id = ASSISTANT_BUILDER_ID
        context_message = "[Context for file generation] "
        if file_path == "Cargo.toml":
            context_message += "You have seen all the Rust source files and test files. Use this context to specify the correct dependencies."
    
    # Add context to building thread
    add_message(building_thread_id, context_message, "user")
    
    # Create event handler with file path
    event_handler = EventHandler(pusher_client, building_thread_id, channel_id, "code-generation", is_code_generation=True)
    event_handler.current_file_path = file_path
    
    # Notify frontend of file generation start
    pusher_client.trigger(channel_id, 'file-generation-status', {
        'filePath': file_path,
        'status': 'generating'
    })
    
    with client.beta.threads.runs.stream(
        thread_id=building_thread_id,  # Using the building thread
        assistant_id=assistant_id,
        event_handler=event_handler
    ) as stream:
        stream.until_done()

    # Send completion status
    pusher_client.trigger(channel_id, 'file-generation-status', {
        'filePath': file_path,
        'status': 'complete',
        'content': event_handler.full_response if hasattr(event_handler, 'full_response') else ""
    })
    
    return event_handler.full_response if hasattr(event_handler, 'full_response') else ""

def save_contract_data(project_name, files_data, user_input):
    """
    Save contract generation data and files to Firestore
    """
    try:
        # Generate a unique ID for this contract
        contract_id = str(uuid.uuid4())
        
        # Create the contract document
        contract_ref = db.collection('contracts').document(contract_id)
        
        # Count different types of files
        file_metrics = {
            'total_files': len(files_data),
            'source_files': len([f for f in files_data.keys() if f.startswith('src/')]),
            'test_files': len([f for f in files_data.keys() if f.startswith('test/')]),
            'other_files': len([f for f in files_data.keys() if not (f.startswith('src/') or f.startswith('test/'))])
        }
        
        # Prepare the contract data
        contract_data = {
            'project_name': project_name,
            'timestamp': datetime.datetime.now(),
            'prompt': user_input,
            'files': {},
            'status': 'completed',
            'file_metrics': file_metrics  # Add file metrics to contract data
        }
        
        # Add each file's content to the contract data
        for file_path, content in files_data.items():
            contract_data['files'][file_path] = {
                'content': content,
                'path': file_path
            }
        
        # Save to Firestore
        contract_ref.set(contract_data)
        
        # Update analytics with aggregated metrics
        analytics_ref = db.collection('analytics').document('contract_generation')
        analytics_ref.set({
            'total_contracts': firestore.Increment(1),
            'total_files_generated': firestore.Increment(file_metrics['total_files']),
            'total_source_files': firestore.Increment(file_metrics['source_files']),
            'total_test_files': firestore.Increment(file_metrics['test_files']),
            'total_other_files': firestore.Increment(file_metrics['other_files']),
            'avg_files_per_contract': firestore.Increment(file_metrics['total_files']),  # We'll divide by total_contracts when querying
            'last_generated': datetime.datetime.now()
        }, merge=True)
        
        return contract_id
    except Exception as e:
        logging.error(f"Error saving contract data: {str(e)}")
        raise e

