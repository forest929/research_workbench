export default function LoadingSpinner({ size = 'md', label }) {
  const sz = size === 'sm' ? 'w-4 h-4' : size === 'lg' ? 'w-8 h-8' : 'w-6 h-6'
  return (
    <div className="flex items-center gap-2">
      <div className={`${sz} border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin`} />
      {label && <span className="text-sm text-slate-500">{label}</span>}
    </div>
  )
}
