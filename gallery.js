const photoModal = document.getElementById('photoModal');
const modalImg = document.getElementById('modalImg');
const modalCaption = document.getElementById('modalCaption');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');

let currentIndex = 0;

function openModal(index) {
  currentIndex = index;
  const photo = images[currentIndex];
  modalImg.src = photo.url;
  modalImg.alt = photo.name;
  modalCaption.textContent = `${photo.name} • ${humanFileSize(photo.size)}`;
  photoModal.classList.remove('hidden');
}

function closeModal() {
  photoModal.classList.add('hidden');
}

function showPrev() {
  if (images.length === 0) return;
  currentIndex = (currentIndex - 1 + images.length) % images.length;
  updateModalContent();
}

function showNext() {
  if (images.length === 0) return;
  currentIndex = (currentIndex + 1) % images.length;
  updateModalContent();
}

function updateModalContent() {
  const photo = images[currentIndex];
  modalImg.src = photo.url;
  modalImg.alt = photo.name;
  modalCaption.textContent = `${photo.name} • ${humanFileSize(photo.size)}`;
}

// Event listeners
prevBtn.addEventListener('click', showPrev);
nextBtn.addEventListener('click', showNext);

// Click to close on background
photoModal.addEventListener('click', (e) => {
  if (e.target === photoModal) closeModal();
});

// Escape key closes modal
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !photoModal.classList.contains('hidden')) {
    closeModal();
  } else if (e.key === 'ArrowLeft') {
    showPrev();
  } else if (e.key === 'ArrowRight') {
    showNext();
  }
});

// Update gallery items to open modal instead of old lightbox
function createMasonryItem(id, src, name, sizeReadable) {
  const wrap = document.createElement('figure');
  wrap.className = 'masonry-item';
  wrap.setAttribute('data-id', id);

  const removeBtn = document.createElement('button');
  removeBtn.className = 'remove-btn';
  removeBtn.type = 'button';
  removeBtn.title = 'Remove photo';
  removeBtn.innerHTML = '✕';
  removeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    removeImage(id);
  });

  const img = document.createElement('img');
  img.src = src;
  img.alt = name;
  img.loading = 'lazy';
  img.tabIndex = 0;
  img.style.cursor = 'zoom-in';
  img.addEventListener('click', () => {
    const index = images.findIndex(p => p.id === id);
    if (index !== -1) openModal(index);
  });

  const caption = document.createElement('figcaption');
  caption.className = 'mt-2 text-xs text-neutral-500 dark:text-neutral-400';
  caption.textContent = `${name} • ${sizeReadable}`;

  wrap.appendChild(removeBtn);
  wrap.appendChild(img);
  wrap.appendChild(caption);

  return wrap;
}
