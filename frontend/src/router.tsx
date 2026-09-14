import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { PeoplePage } from './features/resources/PeoplePage'
import { InfrastructurePage } from './features/resources/InfrastructurePage'
import { ProjectsPage } from './features/projects/ProjectsPage'
import { PlanningPage } from './features/planning/PlanningPage'
import { GanttPage } from './features/gantt/GanttPage'
import { SettingsPage } from './features/settings/SettingsPage'
import { WorkingTimePage } from './features/workingtime/WorkingTimePage'
import { AuditPage } from './features/audit/AuditPage'
import { BaselinesPage } from './features/baselines/BaselinesPage'
import { MyPlanPage } from './features/me/MyPlanPage'
import { LoginPage } from './features/auth/LoginPage'
import { SetupPage } from './features/auth/SetupPage'
import { OIDCCallbackPage } from './features/auth/OIDCCallbackPage'
import { UserManagementPage } from './features/admin/UserManagementPage'
import { HelpPage } from './features/help/HelpPage'

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/setup',
    element: <SetupPage />,
  },
  {
    path: '/auth/oidc/callback',
    element: <OIDCCallbackPage />,
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'people', element: <PeoplePage /> },
          { path: 'infrastructure', element: <InfrastructurePage /> },
          { path: 'projects', element: <ProjectsPage /> },
          { path: 'planning', element: <PlanningPage /> },
          { path: 'gantt', element: <GanttPage /> },
          { path: 'my-plan', element: <MyPlanPage /> },
          { path: 'conflicts', element: <Navigate to="/planning" replace /> },
          { path: 'working-time', element: <WorkingTimePage /> },
          { path: 'audit', element: <AuditPage /> },
          { path: 'baselines', element: <BaselinesPage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: 'admin/users', element: <UserManagementPage /> },
          { path: 'help', element: <HelpPage /> },
          { path: 'help/:slug', element: <HelpPage /> },
          // Redirects for removed routes
          { path: 'project-overview', element: <Navigate to="/" replace /> },
          { path: 'templates', element: <Navigate to="/projects" replace /> },
        ],
      },
    ],
  },
])
