import { lazy, Suspense } from 'react'
import { Navigate } from 'react-router-dom'
import type { RouteObject } from 'react-router-dom'
import MainLayout from '../layouts/MainLayout'
import AuthLayout from '../layouts/AuthLayout'
import LoadingSkeleton from '../components/common/LoadingSkeleton'

const Login = lazy(() => import('../pages/Login'))
const NoteList = lazy(() => import('../pages/NoteList'))
const NoteEditor = lazy(() => import('../pages/NoteEditor'))
const AIChat = lazy(() => import('../pages/AIChat'))
const Sessions = lazy(() => import('../pages/Sessions'))
const Usage = lazy(() => import('../pages/Usage'))
const KnowledgeBase = lazy(() => import('../pages/KnowledgeBase'))
const DailyReview = lazy(() => import('../pages/DailyReview'))
const Profile = lazy(() => import('../pages/Profile'))
const Settings = lazy(() => import('../pages/Settings'))
const AboutUs = lazy(() => import('../pages/AboutUs'))
const GraphPage = lazy(() => import('../pages/GraphPage'))

const LazyLoad = ({ children }: { children: React.ReactNode }) => (
  <Suspense fallback={<LoadingSkeleton />}>{children}</Suspense>
)

const routes: RouteObject[] = [
  { path: '/register', element: <Navigate to="/login" replace /> },
  {
    path: '/login',
    element: <AuthLayout />,
    children: [{ index: true, element: <LazyLoad><Login /></LazyLoad> }],
  },
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <LazyLoad><NoteList /></LazyLoad> },
      { path: 'notes', element: <LazyLoad><NoteList /></LazyLoad> },
      { path: 'notes/:id', element: <LazyLoad><NoteEditor /></LazyLoad> },
      { path: 'notes/new', element: <LazyLoad><NoteEditor /></LazyLoad> },
      { path: 'chat', element: <LazyLoad><AIChat /></LazyLoad> },
      { path: 'chat/:sessionId', element: <LazyLoad><AIChat /></LazyLoad> },
      { path: 'sessions', element: <LazyLoad><Sessions /></LazyLoad> },
      { path: 'usage', element: <LazyLoad><Usage /></LazyLoad> },
      { path: 'review', element: <LazyLoad><DailyReview /></LazyLoad> },
      { path: 'knowledge', element: <LazyLoad><KnowledgeBase /></LazyLoad> },
      { path: 'profile', element: <LazyLoad><Profile /></LazyLoad> },
      { path: 'settings', element: <LazyLoad><Settings /></LazyLoad> },
      { path: 'about', element: <LazyLoad><AboutUs /></LazyLoad> },
      { path: 'graph', element: <LazyLoad><GraphPage /></LazyLoad> },
    ],
  },
]

export default routes
