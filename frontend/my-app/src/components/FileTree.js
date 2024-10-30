import React, { useState } from 'react';
import { ChevronRight, ChevronDown, Folder, FileText, Loader } from 'lucide-react';

const FileTree = ({ structure, onSelectFile, filesState, initiallyExpanded = [] }) => {
  const [expanded, setExpanded] = useState(initiallyExpanded);

  const toggleFolder = (path) => {
    setExpanded((prev) => {
      if (prev.includes(path)) {
        return prev.filter(item => item !== path);
      } else {
        return [...prev, path];
      }
    });
  };

  const renderTree = (items, level = 0) => {
    return items.map((item) => (
      <div key={item.path} style={{ marginLeft: `${level * 16}px` }}>
        {item.type === 'folder' ? (
          <div>
            <div
              className={`flex items-center py-1 px-2 hover:bg-gray-700 rounded cursor-pointer text-gray-300 hover:text-white transition-colors`}
              onClick={() => toggleFolder(item.path)}
            >
              {expanded.includes(item.path) ? (
                <ChevronDown className="h-4 w-4 mr-1 text-blue-400" />
              ) : (
                <ChevronRight className="h-4 w-4 mr-1 text-blue-400" />
              )}
              <Folder className="h-4 w-4 mr-2 text-blue-400" />
              <span className="text-sm">{item.name}</span>
            </div>
            {expanded.includes(item.path) && item.children && renderTree(item.children, level + 1)}
          </div>
        ) : (
          <div
            className={`flex items-center py-1 px-2 rounded cursor-pointer text-sm ${
              filesState[item.path]?.isSelected
                ? 'bg-blue-600 text-white'
                : 'text-gray-300 hover:bg-gray-700 hover:text-white'
            } ${
              filesState[item.path]?.status === 'generating' 
                ? 'bg-green-900' 
                : ''
            } transition-colors`}
            onClick={() => onSelectFile(item.path)}
          >
            <FileText className="h-4 w-4 mr-2 text-gray-400" />
            <span>{item.name}</span>
            {filesState[item.path]?.status === 'generating' && (
              <Loader className="h-3 w-3 ml-2 animate-spin" />
            )}
          </div>
        )}
      </div>
    ));
  };

  return (
    <div className="overflow-auto max-h-[calc(100vh-32px)]">
      {renderTree(structure)}
    </div>
  );
}

export default FileTree;
