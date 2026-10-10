import { useState, useEffect, useRef } from 'react'

const PROVIDERS = [
  { id: 'gemini',    name: 'Google Gemini' },
  { id: 'openai',   name: 'OpenAI GPT'    },
  { id: 'anthropic',name: 'Anthropic Claude'},
]

interface AttachedImage {
  id: string
  url: string
  width: number
  height: number
}

// Hàm resize ảnh giữ tỉ lệ sao cho max(width, height) <= maxSide (mặc định 1600px)
function resizeImage(file: File, maxSide = 1600): Promise<AttachedImage> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const img = new Image()
      img.onload = () => {
        let width = img.width
        let height = img.height

        if (width > maxSide || height > maxSide) {
          if (width > height) {
            height = Math.round((height * maxSide) / width)
            width = maxSide
          } else {
            width = Math.round((width * maxSide) / height)
            height = maxSide
          }
        }

        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          return resolve({
            id: Math.random().toString(36).substring(2, 9),
            url: img.src,
            width: img.width,
            height: img.height,
          })
        }

        ctx.drawImage(img, 0, 0, width, height)
        resolve({
          id: Math.random().toString(36).substring(2, 9),
          url: canvas.toDataURL('image/jpeg', 0.85),
          width,
          height,
        })
      }
      img.onerror = reject
      img.src = e.target?.result as string
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function GenerateTab() {
  const [provider, setProvider] = useState('gemini')
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [problemName, setProblemName] = useState('')
  const [statement, setStatement] = useState('')
  const [images, setImages] = useState<AttachedImage[]>([])
  const [cppCode, setCppCode] = useState('')
  const [testCount, setTestCount] = useState(20)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<object | null>(null)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetch(`/api/models?provider=${provider}`)
      .then(r => r.json())
      .then(d => {
        setModels(d.models || [])
        setModel(d.models?.[0] || '')
      })
      .catch(() => {})
  }, [provider])

  const processFiles = async (fileList: FileList | File[]) => {
    const validFiles = Array.from(fileList).filter(f => f.type.startsWith('image/'))
    if (!validFiles.length) return
    try {
      const resized = await Promise.all(validFiles.map(f => resizeImage(f, 1600)))
      setImages(prev => [...prev, ...resized])
    } catch {
      setError('Lỗi khi xử lý ảnh, vui lòng thử lại.')
    }
  }

  // Xử lý khi nhấn Ctrl+V / Cmd+V
  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    const imageFiles: File[] = []
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile()
        if (file) imageFiles.push(file)
      }
    }
    if (imageFiles.length > 0) {
      e.preventDefault()
      processFiles(imageFiles)
    }
  }

  const removeImage = (id: string) => {
    setImages(prev => prev.filter(img => img.id !== id))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError(''); setResult(null)
    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          problem_name: problemName,
          text_content: statement,
          images: images.map(img => img.url),
          user_cpp_code: cppCode,
          test_count: testCount,
          api_key: apiKey,
          provider_name: provider,
          model_name: model,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Lỗi không xác định')
      setResult(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} onPaste={handlePaste}>
      <div className="card">
        <div className="row">
          <div className="form-group">
            <label>Provider AI</label>
            <select value={provider} onChange={e => setProvider(e.target.value)}>
              {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Model</label>
            <select value={model} onChange={e => setModel(e.target.value)}>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        </div>
        <div className="form-group">
          <label>API Key</label>
          <input
            type="password"
            placeholder={`${provider === 'gemini' ? 'AIza...' : provider === 'openai' ? 'sk-...' : 'sk-ant-...'}`}
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
          />
        </div>
      </div>

      <div className="card">
        <div className="row">
          <div className="form-group">
            <label>Tên bài tập</label>
            <input
              type="text"
              placeholder="VD: Sắp xếp dãy số"
              value={problemName}
              onChange={e => setProblemName(e.target.value)}
              required
            />
          </div>
          <div className="form-group" style={{ maxWidth: 120 }}>
            <label>Số test</label>
            <input
              type="number" min={1} max={100}
              value={testCount}
              onChange={e => setTestCount(Number(e.target.value))}
            />
          </div>
        </div>

        {/* Khu vực Upload / Paste ảnh đề bài */}
        <div className="form-group">
          <label>Ảnh đề bài (Tùy chọn – Tự động nén ≤ 1600px)</label>
          <div
            className="dropzone"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault()
              if (e.dataTransfer.files) processFiles(e.dataTransfer.files)
            }}
          >
            📸 <strong>Nhấn Ctrl+V / Cmd+V để dán ảnh</strong> hoặc bấm vào đây để chọn ảnh từ máy
            <div style={{ fontSize: '0.75rem', marginTop: 4, color: '#6ee7f7' }}>
              Hỗ trợ kéo thả, dán trực tiếp từ clipboard (ảnh tự động xử lý ≤ 1600px)
            </div>
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              accept="image/*"
              multiple
              onChange={e => {
                if (e.target.files) processFiles(e.target.files)
              }}
            />
          </div>

          {images.length > 0 && (
            <div className="image-gallery">
              {images.map((img, idx) => (
                <div key={img.id} className="image-card">
                  <button
                    type="button"
                    className="remove-btn"
                    title="Xóa ảnh này"
                    onClick={() => removeImage(img.id)}
                  >
                    ✕
                  </button>
                  <img src={img.url} alt={`Trang ${idx + 1}`} />
                  <span className="dimensions">
                    {img.width} × {img.height}px
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="form-group">
          <label>Đề bài (Markdown hoặc văn bản)</label>
          <textarea
            placeholder="Dán nội dung đề bài vào đây (hoặc dán ảnh đề bài ở trên)..."
            value={statement}
            onChange={e => setStatement(e.target.value)}
          />
        </div>
        <div className="form-group">
          <label>Code C++ mẫu <span style={{color:'#6b7280'}}>(tuỳ chọn)</span></label>
          <textarea
            placeholder="#include <bits/stdc++.h>..."
            value={cppCode}
            onChange={e => setCppCode(e.target.value)}
            style={{ minHeight: 100, fontFamily: 'monospace' }}
          />
        </div>
      </div>

      <button className="btn btn-primary" type="submit" disabled={loading || !problemName}>
        {loading && <span className="spinner" />}
        {loading ? 'Đang sinh test...' : '🚀 Sinh test'}
      </button>

      {error && <div className="error">❌ {error}</div>}

      {result && (
        <div className="card" style={{ marginTop: 20, borderColor: '#10b981' }}>
          <h3 style={{ color: '#10b981', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
            ✅ Sinh test thành công!
          </h3>
          <p style={{ marginBottom: 12, fontSize: '0.9rem' }}>
            <strong>📁 Thư mục lưu trên máy:</strong><br />
            <code style={{ background: '#0f1117', color: '#6ee7f7', padding: '4px 8px', borderRadius: 4, display: 'inline-block', marginTop: 4 }}>
              {(result as any).output_dir || (result as any).zip_path}
            </code>
          </p>
          {(result as any).download_url && (
            <a
              href={(result as any).download_url}
              download
              className="btn btn-primary"
              style={{ display: 'inline-block', textAlign: 'center', textDecoration: 'none', marginBottom: 16 }}
            >
              📥 Tải file ZIP bộ test ({(result as any).problem_name}.zip)
            </a>
          )}
          <details style={{ marginTop: 12, cursor: 'pointer' }}>
            <summary style={{ color: '#9ca3af', fontSize: '0.85rem' }}>Xem chi tiết kết quả (JSON)</summary>
            <div className="result">{JSON.stringify(result, null, 2)}</div>
          </details>
        </div>
      )}
    </form>
  )
}

function SettingsTab() {
  return (
    <div className="card">
      <p style={{ color: '#9ca3af' }}>
        Cấu hình API key được lưu tạm thời trong session.<br />
        Để lưu vĩnh viễn, đặt biến môi trường trên server:<br /><br />
        <code style={{ color: '#6ee7f7', background: '#0f1117', padding: '2px 8px', borderRadius: 4 }}>
          GEMINI_API_KEY=...<br />
          OPENAI_API_KEY=...<br />
          ANTHROPIC_API_KEY=...
        </code>
      </p>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState<'generate' | 'settings'>('generate')

  return (
    <>
      <h1>AgentCP</h1>
      <p className="subtitle">
        Sinh test tự động cho lập trình thi đấu
        <span className="badge">Multimodal Vision ≤ 1600px ✓</span>
      </p>

      <div className="tabs">
        <button className={`tab ${tab === 'generate' ? 'active' : ''}`} onClick={() => setTab('generate')}>
          ⚡ Sinh test
        </button>
        <button className={`tab ${tab === 'settings' ? 'active' : ''}`} onClick={() => setTab('settings')}>
          ⚙️ Cài đặt
        </button>
      </div>

      {tab === 'generate' && <GenerateTab />}
      {tab === 'settings' && <SettingsTab />}
    </>
  )
}
