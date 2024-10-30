import React, { useState, useEffect, useRef, useMemo, useReducer } from 'react'
import { Button } from "./button"
import { Input } from "./input"
import { ScrollArea } from "./scroll-area"
import { 
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./dropdown-menu"
import { Send, User, Bot, File, Folder, ChevronRight, ChevronDown, Loader, Settings, Download } from "lucide-react"
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { atomDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import Pusher from 'pusher-js'
import FileTree from './FileTree'
import JSZip from 'jszip'
import { saveAs } from 'file-saver'

// Define filesReducer outside the component
const filesReducer = (state, action) => {
  switch (action.type) {
    case 'INITIALIZE_FILES':
      const initialState = {};
      action.files.forEach(file => {
        initialState[file.path] = {
          content: '',
          status: 'pending',
          isSelected: false,
          name: file.name
        };
      });
      return initialState;

    case 'UPDATE_CONTENT':
      console.log('Updating content for:', action.filePath); // Add logging
      return {
        ...state,
        [action.filePath]: {
          ...state[action.filePath],
          content: state[action.filePath]?.content 
            ? state[action.filePath].content + action.content
            : action.content,
          status: 'generating',
        },
      };

    case 'SET_STATUS':
      console.log(`Setting status for ${action.filePath} to ${action.status}`);
      return {
        ...state,
        [action.filePath]: {
          ...state[action.filePath],
          status: action.status,
        },
      };

    case 'SELECT_FILE':
      const updatedState = {};
      Object.keys(state).forEach(path => {
        updatedState[path] = {
          ...state[path],
          isSelected: path === action.filePath,
        };
      });
      return updatedState;

    default:
      return state;
  }
};

function CodeEditor({ code, isGenerating }) {  // Add isGenerating prop
  const memoizedCode = useMemo(() => code, [code]);
  const codeEndRef = useRef(null);
  const codeContainerRef = useRef(null);

  useEffect(() => {
    // Only scroll if file is being generated
    if (isGenerating) {
      codeEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [code, isGenerating]);  // Add isGenerating to dependencies

  // Handle keyboard shortcuts when mouse is over code area
  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
      e.preventDefault();
      
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(codeContainerRef.current);
      selection.removeAllRanges();
      selection.addRange(range);
    }
  };

  return (
    <div 
      ref={codeContainerRef}
      className="h-full w-full overflow-auto"
      onKeyDown={handleKeyDown}
      tabIndex="0"
    >
      <SyntaxHighlighter
        language="rust"
        style={atomDark}
        wrapLines={true}
        wrapLongLines={true}
        customStyle={{
          margin: 0,
          padding: '1rem',
          paddingBottom: '2rem',
          fontSize: '0.75rem',
          backgroundColor: 'transparent',
          minHeight: '100%',
          width: '100%',
          overflow: 'visible',
          WebkitUserSelect: 'text',
          userSelect: 'text',
        }}
      >
        {memoizedCode}
      </SyntaxHighlighter>
      <div ref={codeEndRef} />
    </div>
  );
}

function SoroBuilder() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [generatedFiles, setGeneratedFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [contractName, setContractName] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const inputRef = useRef(null)
  const [pusher, setPusher] = useState(null);
  const [threadId, setThreadId] = useState(null);
  const [streamingMessage, setStreamingMessage] = useState('');
  const messagesEndRef = useRef(null)
  const [channelId, setChannelId] = useState(null);
  const [currentMessage, setCurrentMessage] = useState('');
  const [fileStructure, setFileStructure] = useState([]);
  const [generatingFile, setGeneratingFile] = useState(null);
  const [expandedItems, setExpandedItems] = useState([]);
  const [generatingFiles, setGeneratingFiles] = useState({});
  const [fileContents, setFileContents] = useState({});
  const codeEndRef = useRef(null); // Add a ref for the code end

  // Now use the reducer after it's been defined
  const [filesState, dispatch] = useReducer(filesReducer, {});

  useEffect(() => {
    // Generate a new channel ID
    const newChannelId = `user-${Date.now()}`;
    setChannelId(newChannelId);

    // Initialize Pusher
    const pusherInstance = new Pusher('--------------', {
      cluster: 'eu'
    });

    setPusher(pusherInstance);

    // Subscribe to the chat response channel
    const channel = pusherInstance.subscribe(newChannelId);

    // Set up event listeners for different types of events
    channel.bind('chat-response', handleChatResponse);
    channel.bind('code-chunk', handleCodeChunk);
    channel.bind('file-generation-status', handleFileStatus);
    channel.bind('initial-structure', handleInitialStructure);
    channel.bind('error', handleError); // Add error handler

    return () => {
        if (pusherInstance) {
            pusherInstance.unsubscribe(newChannelId);
            pusherInstance.disconnect();
        }
    };
  }, []);

  const handleChatResponse = (data) => {
    if (data.message_start) {
        setCurrentMessage('');
        setIsLoading(false);
    } else if (data.is_complete) {
        // Add the complete message to the messages array
        if (data.message && data.message.trim()) {
            setMessages(prevMessages => [...prevMessages, { 
                sender: 'ai', 
                content: data.message  // Use the complete message from backend
            }]);
        }
        setCurrentMessage('');  // Clear the streaming message
        setIsLoading(false);
    } else if (data.message) {
        // Only update currentMessage for streaming
        setCurrentMessage(prev => prev + data.message);
    }

    if (data.run_completed) {
        setIsLoading(false);
    }
  };

  // Update handleInitialStructure to initialize filesState
  const handleInitialStructure = (data) => {
    console.log("Received initial structure:", data.structure);
    setFileStructure(data.structure);
    setContractName(data.structure[0].name);
    
    // Get all files from the structure
    const allFiles = [];
    const walkStructure = (items) => {
      items.forEach(item => {
        if (item.type === 'file') {
          allFiles.push(item);
        }
        if (item.children) {
          walkStructure(item.children);
        }
      });
    };
    walkStructure(data.structure);
    
    // Initialize filesState with all files
    dispatch({
      type: 'INITIALIZE_FILES',
      files: allFiles
    });
    
    // Automatically expand all folders
    const foldersToExpand = data.structure
      .flatMap(item => getAllFolderPaths(item))
      .filter(Boolean);
    setExpandedItems(foldersToExpand);
  };

  const getAllFolderPaths = (item) => {
    if (item.type === 'folder') {
      return [item.path, ...(item.children || []).flatMap(getAllFolderPaths)];
    }
    return [];
  };

  // Update handleCodeChunk to use the new state management
  const handleCodeChunk = (data) => {
    if (!data.filePath) return;
    
    console.log('Received code chunk for:', data.filePath); // Add logging
    
    dispatch({
      type: 'UPDATE_CONTENT',
      filePath: data.filePath,
      content: data.content
    });
  };

  // Update handleFileStatus to use the new state management
  const handleFileStatus = (data) => {
    const { filePath, status } = data;
    
    dispatch({
      type: 'SET_STATUS',
      filePath,
      status
    });
    
    if (status === 'generating') {
      handleFileSelect(filePath);
    }
  };

  // Update handleFileSelect to use the new state management
  const handleFileSelect = (filePath) => {
    console.log(`Selecting file: ${filePath}`);
    dispatch({
      type: 'SELECT_FILE',
      filePath
    });
    setSelectedFile(filePath);
  };

  const updateFileInStructure = (structure, path, contentUpdater, status = 'complete') => {
    return structure.map(item => {
      if (item.path === path) {
        const newContent = typeof contentUpdater === 'function' 
          ? contentUpdater(item)
          : contentUpdater;
        return { ...item, content: newContent, status };
      } else if (item.children) {
        return { ...item, children: updateFileInStructure(item.children, path, contentUpdater, status) };
      }
      return item;
    });
  };

  const handleSendMessage = async () => {
    if (input.trim()) {
      // Add user message immediately
      setMessages(prevMessages => [...prevMessages, { 
        sender: 'user', 
        content: input.trim() 
      }]);
      setInput('');
      setIsLoading(true);
      
      try {
        const response = await fetch('your-backend-url', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ 
            input: input.trim(),
            thread_id: threadId,
            channel_id: channelId
          }),
        });
        const data = await response.json();
        setThreadId(data.thread_id);
      } catch (error) {
        console.error('Error:', error);
        setIsLoading(false);
        // Add error message to chat
        setMessages(prevMessages => [...prevMessages, { 
          sender: 'ai', 
          content: 'Error: Failed to send message. Please try again.',
          isError: true 
        }]);
      }

      if (inputRef.current) {
        inputRef.current.focus();
      }
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && input.trim()) {
      handleSendMessage()
    }
  }

  const handleRestartSession = () => {
    setMessages([])
    setInput('')
    setGeneratedFiles([])
    setSelectedFile(null)
    setContractName(null)
    setIsLoading(false)

    // Unsubscribe from the current channel and disconnect Pusher
    if (pusher) {
      pusher.unsubscribe('my-channel')
      pusher.disconnect()
    }

    // Reinitialize Pusher with a new channel
    const newPusherInstance = new Pusher('--------------', {
      cluster: 'eu'
    });
    setPusher(newPusherInstance);
    newPusherInstance.subscribe('my-channel').bind('chat-response', function(data) {
      setMessages(prev => [...prev, { sender: 'ai', content: data.message }]);
      setIsLoading(false);
    });
  }

  // Update the scrollToBottom function to be more aggressive with the scroll
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }) // Changed from "smooth" to "instant"
  }

  // Add a new useEffect specifically for currentMessage
  useEffect(() => {
    scrollToBottom()
  }, [currentMessage])

  // Keep the existing useEffect for messages and streamingMessage
  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingMessage])

  const handleDownload = async () => {
    const zip = new JSZip();

    const addToZip = (items, currentPath = '') => {
      items.forEach(item => {
        const itemPath = currentPath ? `${currentPath}/${item.name}` : item.name;
        
        if (item.type === 'file') {
          const content = filesState[item.path]?.content || '';
          zip.file(itemPath, content);
        } else if (item.type === 'folder' && item.children) {
          addToZip(item.children, itemPath);
        }
      });
    };

    addToZip(fileStructure);

    const content = await zip.generateAsync({ type: "blob" });
    saveAs(content, `${contractName || 'project'}.zip`);
  };

  // Add error handler
  const handleError = (data) => {
    console.error('Error:', data.message);
    setIsLoading(false);
    // Optionally show error message to user
    setMessages(prev => [...prev, { 
        sender: 'ai', 
        content: `Error: ${data.message}. Please try again.`,
        isError: true 
    }]);
  };

  // Update message rendering to handle errors
  const renderMessage = (message, index) => (
    <div key={index} className={`mb-4 ${message.sender === 'user' ? 'text-right' : 'text-left'}`}>
      <div className={`inline-block p-3 rounded-lg max-w-[75%] ${
        message.isError 
          ? 'bg-red-900/50' 
          : message.sender === 'user' 
            ? 'bg-blue-600/50 ml-auto' 
            : 'bg-gradient-to-r from-gray-700 to-gray-600'
      }`}>
        <div className={`flex items-center mb-1 ${
          message.sender === 'user' ? 'justify-end' : 'justify-start'
        }`}>
          {message.sender === 'user' ? (
            <>
              <span className="font-semibold text-xs mr-2">You</span>
              <User className="h-3 w-3" />
            </>
          ) : (
            <>
              <Bot className="h-3 w-3 mr-2" />
              <span className="font-semibold text-xs">AI</span>
            </>
          )}
        </div>
        <p className="text-xs whitespace-pre-wrap text-left">{message.content}</p>
      </div>
    </div>
  );

  // Add a spinner component
  const LoadingSpinner = () => (
    <div className="flex justify-center items-center mb-4">
      <Loader className="h-5 w-5 animate-spin text-teal-400" />
    </div>
  );

  const scrollToCodeBottom = () => {
    codeEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Add a useEffect to scroll when the selected file's content changes
  useEffect(() => {
    if (selectedFile && filesState[selectedFile]?.status === 'generating') {
      scrollToCodeBottom();
    }
  }, [filesState[selectedFile]?.content, selectedFile]);

  // Update the code editor section to use filesState

  const renderCodeEditor = () => {
    const currentFile = filesState[selectedFile];
    console.log(`Rendering CodeEditor for file: ${selectedFile}`, currentFile);

    return (
      <div className="h-[calc(100vh-8rem)] bg-gray-800 rounded-lg overflow-hidden flex flex-col">
        {selectedFile ? (
          <>
            {/* Fixed Header */}
            <div className="flex items-center px-4 py-2 bg-gray-700 border-b border-gray-600 sticky top-0 z-10">
              <span className="text-sm text-gray-300">{selectedFile}</span>
              {currentFile?.status === 'generating' && (
                <span className="ml-2 text-xs text-teal-400 flex items-center">
                  <Loader className="h-4 w-4 animate-spin mr-1" />
                  Generating...
                </span>
              )}
            </div>
            {/* Scrollable Code Container */}
            <div className="flex-1 overflow-auto">
              <CodeEditor 
                code={currentFile?.content || ''} 
                isGenerating={currentFile?.status === 'generating'}  // Pass generating status
              />
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm">Select a file to view code</p>
          </div>
        )}
      </div>
    );
  };
  return (
    <div className="flex flex-col h-screen bg-gradient-to-br from-gray-900 to-gray-800 text-white">
      {/* Add a style tag for custom scrollbar styling */}
      <style jsx global>{`
        ::-webkit-scrollbar {
          width: 10px;
        }
        ::-webkit-scrollbar-track {
          background: #1f2937; /* Adjust this color to match your background */
        }
        ::-webkit-scrollbar-thumb {
          background: #4b5563; /* Adjust this color for the scrollbar thumb */
          border-radius: 5px;
        }
        ::-webkit-scrollbar-thumb:hover {
          background: #6b7280; /* Adjust this color for the scrollbar thumb on hover */
        }
      `}</style>

      <header className="flex items-center justify-between p-3 bg-black bg-opacity-30 backdrop-blur-lg">
        <h1 className="text-base font-bold text-white">MISSIO IA</h1>
        <h2 className="text-xl font-semibold bg-gradient-to-r from-blue-400 via-teal-400 to-green-400 text-transparent bg-clip-text">
          SoroBuilder
        </h2>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="text-gray-300 hover:text-white hover:bg-white/10">
              <Settings className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="bg-gray-800 border-gray-700">
            <DropdownMenuItem 
              onClick={handleRestartSession} 
              className="text-white hover:bg-gray-700 cursor-pointer"
            >
              Restart session
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-full md:w-[38%] p-4 border-r border-gray-700 flex flex-col">
          <ScrollArea className="flex-grow mb-4 pr-4">
            {messages.map((message, index) => renderMessage(message, index))}
            {isLoading && <LoadingSpinner />}  
            {currentMessage && (
              <div className="mb-4 text-left">
                <div className="inline-block p-3 rounded-lg max-w-[75%] bg-gradient-to-r from-gray-700 to-gray-600">
                  <div className="flex items-center mb-1">
                    <Bot className="h-3 w-3 mr-2" />
                    <span className="font-semibold text-xs">AI</span>
                  </div>
                  <p className="text-xs whitespace-pre-wrap">{currentMessage}</p>
                </div>
              </div>
            )}   
            <div ref={messagesEndRef} />
          </ScrollArea>
          <div className="flex">
            <Input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Type your message..."
              className="flex-grow mr-2 bg-gray-800 border-gray-700 text-white focus:ring-2 focus:ring-blue-500 text-sm"
            />
            <Button 
              onClick={handleSendMessage} 
              className="bg-gradient-to-r from-blue-500 to-teal-500 hover:from-blue-600 hover:to-teal-600 transition-all duration-300 px-4 py-2"
              disabled={isLoading || !input.trim()}
            >
              <Send className="h-5 w-5 mr-2" />
              Send
            </Button>
          </div>
        </div>

        <div className="hidden md:flex md:w-[18%] p-4 border-r border-gray-700 flex-col pr-8">
          <h2 className="text-lg font-bold mb-4 text-teal-400 pl-3">Generated Files</h2>
          <ScrollArea className="flex-grow mb-3">
            {fileStructure.length > 0 && (
              <FileTree 
                structure={fileStructure}
                onSelectFile={handleFileSelect}
                filesState={filesState}
                initiallyExpanded={expandedItems}
              />
            )}
          </ScrollArea>
          {fileStructure.length > 0 && (
            <div className="flex justify-center items-center ml-3">
              <Button
                onClick={handleDownload}
                className="bg-gradient-to-r from-blue-500 to-teal-500 hover:from-blue-600 hover:to-teal-600 transition-all duration-300 px-3 py-4 w-60 h-10 text-sm font-semibold"
              >
                <Download className="h-5 w-5 mr-2" />
                Download Project
              </Button>
            </div>
          )}
        </div>

        <div className="hidden md:block w-[41%] p-4 ml-6">
          <h2 className="text-lg font-bold mb-3 text-blue-400 ml-1">Contract Code</h2>
          {renderCodeEditor()}
        </div>
      </div>
    </div>
  )
}

export default SoroBuilder
