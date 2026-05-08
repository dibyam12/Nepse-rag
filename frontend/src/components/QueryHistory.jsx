/**
 * QueryHistory — Left sidebar showing past conversations / queries.
 *
 * Authenticated: Shows saved conversations from API.
 * Anonymous: Shows nothing (incognito mode).
 */
import { MessageSquare, Plus, Trash2, X } from 'lucide-react';
import useChatStore from '../store/chatStore';

export default function QueryHistory({ isOpen, onClose }) {
  const {
    user, conversations, activeConversationId,
    newConversation, switchConversation, deleteConversation,
  } = useChatStore();

  if (!user) {
    return (
      <SidebarShell isOpen={isOpen} onClose={onClose}>
        <div className="flex flex-col items-center justify-center h-full px-6 text-center">
          <MessageSquare size={40} className="text-surface-300 dark:text-surface-600 mb-3" />
          <p className="text-sm text-surface-500 dark:text-surface-400 mb-1 font-medium">
            Incognito Mode
          </p>
          <p className="text-xs text-surface-400 dark:text-surface-500">
            Log in to save your conversation history
          </p>
        </div>
      </SidebarShell>
    );
  }

  return (
    <SidebarShell isOpen={isOpen} onClose={onClose}>
      {/* New Chat button */}
      <div className="p-3 border-b border-surface-200 dark:border-surface-700/50">
        <button
          onClick={() => { newConversation(); onClose(); }}
          className="w-full flex items-center gap-2 px-3 py-2.5 rounded-xl
                     btn-primary text-sm justify-center"
          id="new-chat-btn"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-surface-400">
            No conversations yet
          </div>
        ) : (
          conversations.map((convo) => (
            <div
              key={convo.id}
              className={`group flex items-center gap-2 px-3 py-3 mx-2 my-1 rounded-xl
                         cursor-pointer transition-all duration-150
                         ${activeConversationId === convo.id
                           ? 'bg-brand-50 dark:bg-brand-900/20 text-brand-700 dark:text-brand-300'
                           : 'hover:bg-surface-100 dark:hover:bg-surface-800 text-surface-700 dark:text-surface-300'
                         }`}
              onClick={() => { switchConversation(convo.id); onClose(); }}
            >
              <MessageSquare size={14} className="flex-shrink-0 opacity-60" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{convo.title}</p>
                <p className="text-[10px] text-surface-400 dark:text-surface-500">
                  {convo.message_count || 0} messages
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteConversation(convo.id);
                }}
                className="opacity-0 group-hover:opacity-100
                           p-1 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30
                           text-surface-400 hover:text-red-500
                           transition-all duration-150"
                title="Delete conversation"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))
        )}
      </div>
    </SidebarShell>
  );
}

function SidebarShell({ isOpen, onClose, children }) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:relative z-50 top-0 left-0 h-full w-72
                    bg-white dark:bg-surface-900
                    border-r border-surface-200 dark:border-surface-800
                    flex flex-col
                    transition-transform duration-300 ease-out
                    ${isOpen ? 'translate-x-0' : '-translate-x-full lg:hidden'}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3
                        border-b border-surface-200 dark:border-surface-700/50">
          <h2 className="text-sm font-semibold text-surface-700 dark:text-surface-200">
            History
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg btn-ghost lg:hidden"
          >
            <X size={16} />
          </button>
        </div>

        {children}
      </aside>
    </>
  );
}
