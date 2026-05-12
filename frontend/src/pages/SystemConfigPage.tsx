import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Brain, Bot, Database, Server, KeyRound, Settings, Ticket, BookOpen, Fingerprint } from 'lucide-react';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';

import AIConfigPage from './AIConfigPage';
import AgentProfilesPage from './AgentProfilesPage';
import MCPConfigPage from './MCPConfigPage';
import ServerConfigPage from './ServerConfigPage';
import RolesPage from './RolesPage';
import SettingsPage from './SettingsPage';
import JiraConfigPage from './JiraConfigPage';
import KnowledgeBasePage from './KnowledgeBasePage';
import IdentityProvidersPage from './IdentityProvidersPage';

const TABS = [
  { key: 'ai-providers',    label: 'AI Providers',    icon: Brain,    roles: ['admin'],             component: AIConfigPage },
  { key: 'agent-profiles',  label: 'Agent Profiles',  icon: Bot,      roles: ['admin'],             component: AgentProfilesPage },
  { key: 'mcp-oracle',      label: 'MCP / Oracle',    icon: Database, roles: ['admin'],             component: MCPConfigPage },
  { key: 'jira',            label: 'Jira / JSM',      icon: Ticket,   roles: ['admin'],             component: JiraConfigPage },
  { key: 'knowledge',        label: 'Knowledge Base',  icon: BookOpen,    roles: ['admin', 'operator'], component: KnowledgeBasePage },
  { key: 'identity',          label: 'Identity / SSO',  icon: Fingerprint, roles: ['admin'],             component: IdentityProvidersPage },
  { key: 'servers',         label: 'Servers / SSH',   icon: Server,   roles: ['admin', 'operator'], component: ServerConfigPage },
  { key: 'roles',           label: 'Roles & RBAC',    icon: KeyRound, roles: ['admin'],             component: RolesPage },
  { key: 'settings',        label: 'Settings',        icon: Settings, roles: ['admin'],             component: SettingsPage },
];

export default function SystemConfigPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const visibleTabs = TABS.filter((t) => user && t.roles.includes(user.role));

  const initialTab = params.get('tab') || visibleTabs[0]?.key || 'ai-providers';
  const [activeTab, setActiveTab] = useState(initialTab);

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    setParams({ tab: key }, { replace: true });
  };

  const current = visibleTabs.find((t) => t.key === activeTab) || visibleTabs[0];
  if (!current) return <p className="text-gray-500">No configuration sections available.</p>;
  const ActiveComponent = current.component;

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-800 mb-6">System Configuration</h2>

      {/* Tab bar */}
      <div className="border-b border-gray-200 mb-6 overflow-x-auto">
        <nav className="-mb-px flex gap-1" aria-label="Configuration tabs">
          {visibleTabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = tab.key === current.key;
            return (
              <button
                key={tab.key}
                onClick={() => handleTabChange(tab.key)}
                className={clsx(
                  'flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                  isActive
                    ? 'border-brand-500 text-brand-600'
                    : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Active section */}
      <ActiveComponent />
    </div>
  );
}
