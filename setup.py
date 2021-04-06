import setuptools

with open('README.md', 'r') as fp:
    readme = fp.read()

setuptools.setup(
    name='wsaio',
    version='0.0.1',
    author='Zavier Mayo',
    description='An event-driven WebSocket library for Python.',
    long_description=readme,
    long_description_content_type='text/markdown',
    url='https://github.com/asleep-cult/wsaio',
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    packages=setuptools.find_packages(),
    python_requires=">=3.7",
)
