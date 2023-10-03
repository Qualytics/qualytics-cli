from setuptools import setup, find_packages

setup(
    name="qualytics-cli",
    packages=find_packages(),
    version="0.1.0",
    license="MIT",
    description="Qualytics CLI",
    author="Qualytics",
    author_email="devops@qualytics.co",
    url="https://www.qualytics.co/",
    keywords=["Qualytics", "Data Quality"],
    include_package_data=True,
    install_requires=[
        "typer[all]",
        "requests"
    ],
    entry_points={
        'console_scripts': ['qualytics=qualytics.qualytics:app']
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7'
)