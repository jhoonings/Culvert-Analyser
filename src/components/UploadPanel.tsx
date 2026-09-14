import { useRef, useState } from 'react';

const MAX_FILE_SIZE = 1000 * 1024 * 1024; // ~1 GB

interface UploadPanelProps {
  onUpload: (options: { file: File; resolution: string; }) => void;
  isProcessing: boolean;
}

export default function UploadPanel({ onUpload, isProcessing }: UploadPanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [resolution, setResolution] = useState<string>("1920x1080");

  // on change event handler, when video is selected we check size
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>): void {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_FILE_SIZE) {
      alert('File too large, reduce size to less than 1 GB');
      if (fileInputRef.current) fileInputRef.current.value = '';
      setFileName(null);
      return;
    }
    setFileName(file.name);
  }

  function handleUploadClick(): void {
    if (isProcessing) {
      alert('Video currently processing, please wait to try again.');
      return;
    }
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      alert('Please select a video file first!');
      return;
    }
    onUpload({ file, resolution });
  }

  return (
    <div className="upload-panel">
      {/* hidden real file input */}
      <input
        ref={fileInputRef}
        id="videoFile"
        type="file"
        accept="video/*"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />

      {/* styled button that triggers the file input */}
      <button
        className="button icon solid fa-upload"
        onClick={() => fileInputRef.current?.click()}
        disabled={isProcessing}
      >
        {fileName ?? 'Upload Video'}
      </button>

      <label htmlFor="resoSelect">Select In-Game Resolution:</label>
      <select
        id="resoSelect"
        className="select"
        style={{ display: 'inline-block', maxWidth: '100%', width: '100%' }}
        value={resolution}
        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setResolution(e.target.value)}
        disabled={isProcessing}
      >
        <option value="2560x1440">2560x1440</option>
        <option value="1920x1080">1920x1080</option>
        <option value="1366x768">1366x768</option>
        <option value="1280x720">1280x720</option>
        <option value="1024x768">1024x768</option>
      </select>

      <ul className="actions" style={{ marginLeft: '0px' }}>
				<button
        className="button primary"
        onClick={handleUploadClick}
        disabled={isProcessing}>
          {isProcessing ? 'Processing...' : 'Analyse'}
      </button>
			</ul>
      
    </div>
  );
}
